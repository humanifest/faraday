"""Adverse and metamorphic checks for source-composability public development."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

import pytest

import research_machine.literature.composability as composability_module
from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.composability import (
    create_source_composability_evaluation,
    validate_source_composability_boundary,
    verify_source_composability_evaluation,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "source-composability.json"
EXAMPLE_SOURCES = ROOT / "examples" / "source-composability-sources"


def _spec() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _write_spec(
    tmp_path: Path, value: dict, name: str = "spec.json"
) -> tuple[Path, str]:
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path = tmp_path / name
    path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest()


def _copy_sources(tmp_path: Path, name: str = "sources") -> Path:
    root = tmp_path / name
    shutil.copytree(EXAMPLE_SOURCES, root)
    return root


def _create(
    tmp_path: Path,
    value: dict | None = None,
    name: str = "evaluation",
    source_root: Path | None = None,
) -> tuple[dict, Path, Path]:
    specification = _spec() if value is None else value
    path, digest = _write_spec(tmp_path, specification, f"{name}-spec.json")
    sources = source_root or _copy_sources(tmp_path, f"{name}-sources")
    result = create_source_composability_evaluation(
        path, digest, sources, tmp_path / f"{name}.json"
    )
    return result, path, sources


def test_cli_evaluates_and_replays_matched_bytes_without_authority(tmp_path, capsys):
    spec_path, spec_digest = _write_spec(tmp_path, _spec())
    sources = _copy_sources(tmp_path)
    output = tmp_path / "evaluation.json"
    assert main(
        [
            "--json",
            "literature",
            "evaluate-composability",
            "--spec-file",
            str(spec_path),
            "--expected-spec-sha256",
            spec_digest,
            "--source-artifact-root",
            str(sources),
            "--output",
            str(output),
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["source_composability_evaluation_version"] == 3
    assert result["verdict"] == (
        "required_graph_has_unclosed_arrows_with_exact_node_support"
    )
    assert result["first_unclosed_required_arrow_id"] == "local-to-assembled"
    assert result["exactly_supported_node_ids"] == ["local-object"]
    assert result["exactly_supported_nodes"][0]["statement"].startswith(
        "The local object"
    )
    assert result["generic_missing_formula_verdict_permitted"] is False
    assert result["graph_topology"] == {
        "weakly_connected": True,
        "acyclic": True,
        "target_node_ids_topological": True,
    }
    assert len(result["source_artifact_receipts"]) == 3
    assert all(
        receipt["expected_sha256"] == receipt["observed_sha256"]
        and receipt["observed_size_bytes"] > 0
        and receipt["status"] == "matched"
        for receipt in result["source_artifact_receipts"]
    )
    for field in (
        "source_truth_established",
        "source_semantics_established",
        "scientific_validity_established",
        "scientific_evidence_eligible",
        "replication_authority_established",
        "candidate_advancement_eligible",
        "runtime_promotion_authorized",
        "conclusion_authorized",
        "assessor_identity_authenticated",
        "auditor_independence_established",
    ):
        assert result[field] is False

    evaluation_path = output
    assert evaluation_path.is_file()
    assert result["path"] == str(evaluation_path)
    assert main(
        [
            "--json",
            "literature",
            "verify-composability",
            "--spec-file",
            str(spec_path),
            "--expected-spec-sha256",
            spec_digest,
            "--source-artifact-root",
            str(sources),
            "--evaluation-file",
            str(evaluation_path),
            "--expected-evaluation-sha256",
            result["evaluation_sha256"],
        ]
    ) == 0
    replay = json.loads(capsys.readouterr().out)["result"]
    assert replay["status"] == "source_composability_graph_evaluation_replayed"
    assert replay["source_artifact_byte_custody_status"] == (
        "all_declared_source_bytes_matched"
    )
    assert replay["candidate_advancement_eligible"] is False


def test_object_reordering_normalizes_without_changing_first_unclosed_arrow(tmp_path):
    original = _spec()
    reordered = deepcopy(original)
    reordered["source_references"].reverse()
    reordered["nodes"].reverse()
    reordered["required_arrows"].reverse()
    first, _, _ = _create(tmp_path, original, "first")
    second, _, _ = _create(tmp_path, reordered, "second")
    assert second["contract_sha256"] == first["contract_sha256"]
    assert second["first_unclosed_required_arrow"] == (
        first["first_unclosed_required_arrow"]
    )


def _three_node_graph() -> dict:
    spec = _spec()
    spec["target_node_ids"] = ["node-a", "node-b", "node-c"]
    spec["nodes"] = [
        {**spec["nodes"][0], "node_id": "node-a"},
        {
            **spec["nodes"][0],
            "node_id": "node-b",
            "statement": "The middle exact object is declared.",
        },
        {**spec["nodes"][1], "node_id": "node-c"},
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
    return spec


def test_relabeling_cannot_replace_declared_arrow_order_with_lexical_order(tmp_path):
    spec = _three_node_graph()
    original, _, _ = _create(tmp_path, spec, "original")
    assert original["first_unclosed_required_arrow_id"] == "z-first"

    relabeled = deepcopy(spec)
    relabeled["required_arrow_ids"] = ["a-relabeled-first", "z-relabeled-second"]
    for arrow in relabeled["required_arrows"]:
        if arrow["compatibility_requirement"].startswith("First"):
            arrow["arrow_id"] = "a-relabeled-first"
        else:
            arrow["arrow_id"] = "z-relabeled-second"
    relabeled["required_arrows"].reverse()
    changed, _, _ = _create(tmp_path, relabeled, "relabeled")
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
            lambda value: value["nodes"][0]["source_refs"].__setitem__(
                0, "missing-source"
            ),
            "unknown source refs",
        ),
        (
            lambda value: value["nodes"][0]["scope"].pop("carrier"),
            "scope fields do not match",
        ),
        (
            lambda value: value["required_arrows"][0]["scope"].update(
                {"domain": " "}
            ),
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
                {
                    "status": "not_found_in_bounded_search",
                    "source_refs": ["primary-local"],
                }
            ),
            "must cite bounded_search_source_ref",
        ),
        (
            lambda value: value.update({"contract_version": True}),
            "integer 2, not Boolean",
        ),
        (
            lambda value: value["nodes"][0]["scope"].update(
                {"signature": "different signature"}
            ),
            "node signature and dimension must equal",
        ),
        (
            lambda value: value["required_arrows"][0]["scope"].update(
                {"dimension": "different dimension"}
            ),
            "arrow signature and dimension must equal",
        ),
        (
            lambda value: value.update(
                {"target_node_ids": list(reversed(value["target_node_ids"]))}
            ),
            "must be a topological order",
        ),
    ],
)
def test_invalid_contract_fails_before_publication(tmp_path, mutation, message):
    spec = _spec()
    mutation(spec)
    spec_path, digest = _write_spec(tmp_path, spec)
    sources = _copy_sources(tmp_path)
    output = tmp_path / "evaluation"
    with pytest.raises(ValidationError, match=message):
        create_source_composability_evaluation(
            spec_path, digest, sources, output
        )
    assert not output.exists()


def test_disconnected_dependency_graph_is_rejected(tmp_path):
    spec = _three_node_graph()
    spec["target_node_ids"].append("node-d")
    spec["nodes"].append(
        {
            **spec["nodes"][0],
            "node_id": "node-d",
            "statement": "A disconnected exact object is declared.",
        }
    )
    spec["required_arrow_ids"] = ["component-one", "component-two"]
    spec["required_arrows"] = [
        {
            **spec["required_arrows"][0],
            "arrow_id": "component-one",
            "source_node_id": "node-a",
            "target_node_id": "node-b",
        },
        {
            **spec["required_arrows"][0],
            "arrow_id": "component-two",
            "source_node_id": "node-c",
            "target_node_id": "node-d",
        },
    ]
    spec_path, digest = _write_spec(tmp_path, spec)
    sources = _copy_sources(tmp_path)
    with pytest.raises(ValidationError, match="weakly connected"):
        create_source_composability_evaluation(
            spec_path, digest, sources, tmp_path / "evaluation"
        )


def test_cyclic_dependency_graph_is_rejected(tmp_path):
    spec = _spec()
    reverse = {
        **spec["required_arrows"][0],
        "arrow_id": "assembled-to-local",
        "source_node_id": "assembled-object",
        "target_node_id": "local-object",
    }
    spec["required_arrow_ids"].append("assembled-to-local")
    spec["required_arrows"].append(reverse)
    spec_path, digest = _write_spec(tmp_path, spec)
    sources = _copy_sources(tmp_path)
    with pytest.raises(ValidationError, match="must be acyclic"):
        create_source_composability_evaluation(
            spec_path, digest, sources, tmp_path / "evaluation"
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(
            {
                "required_graph_fully_supported_under_declared_exact_support": True,
                "verdict": "required_graph_fully_supported_under_declared_exact_support",
            }
        ),
        lambda value: value.update(
            {"exactly_supported_node_ids": [], "exactly_supported_nodes": []}
        ),
        lambda value: value.update({"generic_missing_formula_verdict_permitted": True}),
        lambda value: value.update({"scientific_evidence_eligible": True}),
        lambda value: value["source_artifact_receipts"][0].update(
            {"observed_size_bytes": 0}
        ),
    ],
)
def test_replay_rejects_false_graph_support_exact_node_erasure_and_authority(
    tmp_path, mutation
):
    result, _, sources = _create(tmp_path)
    evaluation = {
        key: value
        for key, value in result.items()
        if key not in {"path", "evaluation_sha256"}
    }
    mutation(evaluation)
    with pytest.raises(ValidationError, match="does not replay"):
        validate_source_composability_boundary(evaluation, sources)


def test_source_mutation_blocks_replay_even_when_evaluation_bytes_are_unchanged(tmp_path):
    result, spec_path, sources = _create(tmp_path)
    evaluation_path = Path(result["path"])
    (sources / "primary-local.txt").write_text("mutated source bytes\n")
    with pytest.raises(ValidationError, match="artifact SHA-256 mismatch"):
        verify_source_composability_evaluation(
            spec_path,
            result["specification_sha256"],
            sources,
            evaluation_path,
            result["evaluation_sha256"],
        )


@pytest.mark.parametrize("condition", ["missing", "symlink"])
def test_source_removal_or_symlink_substitution_blocks_replay(tmp_path, condition):
    result, spec_path, sources = _create(tmp_path)
    evaluation_path = Path(result["path"])
    target = sources / "primary-local.txt"
    target.unlink()
    if condition == "symlink":
        outside = tmp_path / "outside.txt"
        outside.write_text("outside bytes\n")
        target.symlink_to(outside)
    with pytest.raises(
        ValidationError,
        match=("missing" if condition == "missing" else "symlink"),
    ):
        verify_source_composability_evaluation(
            spec_path,
            result["specification_sha256"],
            sources,
            evaluation_path,
            result["evaluation_sha256"],
        )


def test_path_escape_in_retained_evaluation_is_rejected_during_boundary_replay(tmp_path):
    result, _, sources = _create(tmp_path)
    evaluation = {
        key: value
        for key, value in result.items()
        if key not in {"path", "evaluation_sha256"}
    }
    evaluation["contract"]["source_references"][0]["locator"] = "../outside.txt"
    with pytest.raises(ValidationError, match="safe relative POSIX locator"):
        validate_source_composability_boundary(evaluation, sources)


@pytest.mark.parametrize("condition", ["missing", "directory", "symlink"])
def test_missing_nonregular_or_symlink_source_fails_closed(tmp_path, condition):
    spec_path, digest = _write_spec(tmp_path, _spec())
    sources = _copy_sources(tmp_path)
    target = sources / "primary-local.txt"
    target.unlink()
    if condition == "directory":
        target.mkdir()
    elif condition == "symlink":
        outside = tmp_path / "outside.txt"
        outside.write_text("outside bytes\n")
        target.symlink_to(outside)
    with pytest.raises(
        ValidationError,
        match=(
            "missing"
            if condition == "missing"
            else "regular file|symlink"
        ),
    ):
        create_source_composability_evaluation(
            spec_path, digest, sources, tmp_path / "evaluation"
        )


@pytest.mark.parametrize(
    "locator", ["../outside.txt", "/absolute.txt", "nested/../../outside.txt", "a//b"]
)
def test_unsafe_source_locator_is_rejected(tmp_path, locator):
    spec = _spec()
    spec["source_references"][0]["locator"] = locator
    spec_path, digest = _write_spec(tmp_path, spec)
    sources = _copy_sources(tmp_path)
    with pytest.raises(ValidationError, match="safe relative POSIX locator"):
        create_source_composability_evaluation(
            spec_path, digest, sources, tmp_path / "evaluation"
        )


@pytest.mark.parametrize(
    "locator",
    [
        "primary-\nlocal.txt",
        "primary-local.txt\n",
        "primary-\x00local.txt",
        "primary-\x1flocal.txt",
        "primary-\x7flocal.txt",
    ],
)
def test_locator_control_characters_are_rejected_by_schema_and_runtime(
    tmp_path, locator
):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (ROOT / "schemas" / "source-composability.schema.json").read_text()
    )
    spec = _spec()
    spec["source_references"][0]["locator"] = locator
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(spec, schema)

    spec_path, digest = _write_spec(tmp_path, spec)
    sources = _copy_sources(tmp_path)
    with pytest.raises(ValidationError, match="NUL, newline, or control"):
        create_source_composability_evaluation(
            spec_path, digest, sources, tmp_path / "evaluation"
        )


def test_intermediate_symlink_in_source_locator_is_rejected(tmp_path):
    spec = _spec()
    spec["source_references"][0]["locator"] = "nested/primary-local.txt"
    spec_path, digest = _write_spec(tmp_path, spec)
    sources = _copy_sources(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.copy2(EXAMPLE_SOURCES / "primary-local.txt", outside / "primary-local.txt")
    (sources / "nested").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValidationError, match="symlink"):
        create_source_composability_evaluation(
            spec_path, digest, sources, tmp_path / "evaluation"
        )


def test_source_root_itself_must_not_be_a_symlink(tmp_path):
    actual = _copy_sources(tmp_path, "actual")
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)
    spec_path, digest = _write_spec(tmp_path, _spec())
    with pytest.raises(ValidationError, match="root must be a non-symlink directory"):
        create_source_composability_evaluation(
            spec_path, digest, linked, tmp_path / "evaluation"
        )


def test_no_follow_support_is_mandatory(tmp_path, monkeypatch):
    spec_path, digest = _write_spec(tmp_path, _spec())
    sources = _copy_sources(tmp_path)
    monkeypatch.delattr(composability_module.os, "O_NOFOLLOW")
    with pytest.raises(ValidationError, match="requires operating-system O_NOFOLLOW"):
        create_source_composability_evaluation(
            spec_path, digest, sources, tmp_path / "evaluation"
        )


def test_in_place_source_mutation_with_restored_mtime_is_rejected(
    tmp_path, monkeypatch
):
    spec_path, digest = _write_spec(tmp_path, _spec())
    sources = _copy_sources(tmp_path)
    target = sources / "primary-assembled.txt"
    original_bytes = target.read_bytes()
    original_metadata = target.stat()
    original_fstat = composability_module.os.fstat
    regular_fstat_calls = 0

    def mutate_before_closed_fstat(descriptor):
        nonlocal regular_fstat_calls
        observed = original_fstat(descriptor)
        if stat.S_ISREG(observed.st_mode):
            regular_fstat_calls += 1
            if regular_fstat_calls == 2:
                target.write_bytes(b"X" * len(original_bytes))
                os.utime(
                    target,
                    ns=(original_metadata.st_atime_ns, original_metadata.st_mtime_ns),
                )
                observed = original_fstat(descriptor)
                assert observed.st_mtime_ns == original_metadata.st_mtime_ns
                assert observed.st_ctime_ns != original_metadata.st_ctime_ns
        return observed

    monkeypatch.setattr(composability_module.os, "fstat", mutate_before_closed_fstat)
    with pytest.raises(ValidationError, match="changed while hashing"):
        create_source_composability_evaluation(
            spec_path, digest, sources, tmp_path / "evaluation"
        )


def test_changed_spec_or_evaluation_bytes_fail_hash_bound_replay(tmp_path):
    result, spec_path, sources = _create(tmp_path)
    evaluation_path = Path(result["path"])

    changed_spec = _spec()
    changed_spec["contract_id"] = "changed-contract"
    _write_spec(tmp_path, changed_spec, spec_path.name)
    with pytest.raises(ValidationError, match="specification does not match"):
        verify_source_composability_evaluation(
            spec_path,
            result["specification_sha256"],
            sources,
            evaluation_path,
            result["evaluation_sha256"],
        )

    spec_path, digest = _write_spec(tmp_path, _spec(), spec_path.name)
    evaluation_path.write_bytes(evaluation_path.read_bytes() + b" ")
    with pytest.raises(ValidationError, match="evaluation does not match"):
        verify_source_composability_evaluation(
            spec_path,
            digest,
            sources,
            evaluation_path,
            result["evaluation_sha256"],
        )


def test_preexisting_empty_destination_is_never_replaced(tmp_path):
    spec_path, digest = _write_spec(tmp_path, _spec())
    sources = _copy_sources(tmp_path)
    output = tmp_path / "evaluation"
    output.mkdir()
    with pytest.raises(ValidationError, match="already exists"):
        create_source_composability_evaluation(
            spec_path, digest, sources, output
        )
    assert output.is_dir()
    assert list(output.iterdir()) == []


def _install_substitute(path: Path, kind: str, symlink_target: Path) -> None:
    if kind == "regular_file":
        path.write_text("attacker replacement\n", encoding="utf-8")
    elif kind == "directory":
        path.mkdir()
    else:
        path.symlink_to(symlink_target)


@pytest.mark.parametrize("kind", ["regular_file", "directory", "symlink"])
def test_preopen_output_substitution_is_a_collision_and_never_replaced(
    tmp_path, monkeypatch, kind
):
    spec_path, digest = _write_spec(tmp_path, _spec())
    sources = _copy_sources(tmp_path)
    output = tmp_path / "race-output.json"
    symlink_target = tmp_path / "attacker-target.txt"
    symlink_target.write_text("attacker target\n", encoding="utf-8")
    original_open = composability_module.os.open
    injected = False

    def substituting_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal injected
        if path == output.name and flags & os.O_CREAT and not injected:
            _install_substitute(output, kind, symlink_target)
            injected = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(composability_module.os, "open", substituting_open)
    with pytest.raises(ValidationError, match="already exists"):
        create_source_composability_evaluation(
            spec_path, digest, sources, output
        )
    assert injected is True
    if kind == "regular_file":
        assert output.read_text(encoding="utf-8") == "attacker replacement\n"
    elif kind == "directory":
        assert output.is_dir()
        assert list(output.iterdir()) == []
    else:
        assert output.is_symlink()
        assert symlink_target.read_text(encoding="utf-8") == "attacker target\n"


def test_write_failure_leaves_atomically_created_output(tmp_path, monkeypatch):
    spec_path, digest = _write_spec(tmp_path, _spec())
    sources = _copy_sources(tmp_path)
    output = tmp_path / "evaluation.json"

    def failing_write(_descriptor, _encoded):
        raise OSError("injected write failure")

    monkeypatch.setattr(composability_module, "_write_output_file", failing_write)
    with pytest.raises(ValidationError, match="failed after atomic creation"):
        create_source_composability_evaluation(
            spec_path, digest, sources, output
        )
    assert output.is_file()
    assert output.stat().st_size == 0


@pytest.mark.parametrize("kind", ["regular_file", "directory", "symlink"])
def test_postopen_output_substitution_cannot_redirect_or_report_success(
    tmp_path, monkeypatch, kind
):
    spec_path, digest = _write_spec(tmp_path, _spec())
    sources = _copy_sources(tmp_path)
    output = tmp_path / "evaluation.json"
    moved_output = tmp_path / "moved-created-output.json"
    symlink_target = tmp_path / "attacker-target.txt"
    symlink_target.write_text("attacker target\n", encoding="utf-8")
    original_write = composability_module._write_output_file
    injected = False

    def substitute_after_open(descriptor, encoded):
        nonlocal injected
        if not injected:
            output.rename(moved_output)
            _install_substitute(output, kind, symlink_target)
            injected = True
        original_write(descriptor, encoded)

    monkeypatch.setattr(
        composability_module, "_write_output_file", substitute_after_open
    )
    with pytest.raises(
        ValidationError, match="no longer names the atomically created"
    ):
        create_source_composability_evaluation(
            spec_path, digest, sources, output
        )
    assert injected is True
    assert moved_output.is_file()
    moved_payload = json.loads(moved_output.read_text(encoding="utf-8"))
    assert moved_payload["source_composability_evaluation_version"] == 3
    if kind == "regular_file":
        assert output.read_text(encoding="utf-8") == "attacker replacement\n"
    elif kind == "directory":
        assert output.is_dir()
        assert list(output.iterdir()) == []
    else:
        assert output.is_symlink()
        assert symlink_target.read_text(encoding="utf-8") == "attacker target\n"


def test_boolean_contract_version_is_rejected_by_schema_and_runtime(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (ROOT / "schemas" / "source-composability.schema.json").read_text()
    )
    spec = _spec()
    spec["contract_version"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(spec, schema)

    spec_path, digest = _write_spec(tmp_path, spec)
    sources = _copy_sources(tmp_path)
    with pytest.raises(ValidationError, match="integer 2, not Boolean"):
        create_source_composability_evaluation(
            spec_path, digest, sources, tmp_path / "evaluation"
        )


def test_superseded_v1_contract_is_rejected_by_schema_and_runtime(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (ROOT / "schemas" / "source-composability.schema.json").read_text()
    )
    spec = _spec()
    spec["contract_version"] = 1
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(spec, schema)

    spec_path, digest = _write_spec(tmp_path, spec)
    sources = _copy_sources(tmp_path)
    with pytest.raises(ValidationError, match="integer 2"):
        create_source_composability_evaluation(
            spec_path, digest, sources, tmp_path / "evaluation.json"
        )


@pytest.mark.parametrize("version", [1, 2])
def test_superseded_evaluation_versions_are_nonreplayable(tmp_path, version):
    result, _, sources = _create(tmp_path)
    evaluation = {
        key: value
        for key, value in result.items()
        if key not in {"path", "evaluation_sha256"}
    }
    evaluation["source_composability_evaluation_version"] = version
    with pytest.raises(ValidationError, match="does not replay"):
        validate_source_composability_boundary(evaluation, sources)


def test_direct_limitation_is_distinct_and_unclosed(tmp_path):
    spec = _spec()
    spec["required_arrows"][0].update(
        {
            "status": "direct_limitation",
            "source_refs": ["primary-assembled"],
            "assessment": (
                "The cited source states a direct scope limitation for this arrow."
            ),
        }
    )
    result, _, _ = _create(tmp_path, spec)
    assert result["arrow_status_counts"]["direct_limitation"] == 1
    assert result["arrow_status_counts"]["not_found_in_bounded_search"] == 0
    assert result[
        "required_graph_fully_supported_under_declared_exact_support"
    ] is False


def test_all_exact_graph_support_does_not_grant_scientific_authority(tmp_path):
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
            "assessment": (
                "The cited primary fixtures state the exact directed compatibility."
            ),
        }
    )
    result, _, _ = _create(tmp_path, spec)
    assert result[
        "required_graph_fully_supported_under_declared_exact_support"
    ] is True
    assert result["verdict"] == (
        "required_graph_fully_supported_under_declared_exact_support"
    )
    assert result["first_unclosed_required_arrow"] is None
    assert result["scientific_validity_established"] is False
