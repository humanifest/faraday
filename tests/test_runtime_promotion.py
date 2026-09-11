"""Read-only runtime-promotion audit regressions using synthetic fixtures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from research_machine.domain.models import QualityGateStatus
from research_machine.executors.notebook_freeze_bundle import (
    create_notebook_freeze_input_bundle,
)
from research_machine.interfaces.runtime_promotion import (
    audit_runtime_promotion,
)
from research_machine.interfaces.cli import main
from test_execution import (
    CODE_HASH,
    ENVIRONMENT_HASH,
    SEED_REVEAL,
    frozen_formal_protocol,
    prepared_service,
)
from test_notebook_freeze_bundle import _bundle_inputs


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> str:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return _sha256(path)


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _clean_runtime_repository(path: Path) -> str:
    path.mkdir()
    _git(path, "init", "--quiet")
    _git(path, "config", "user.name", "Synthetic Test")
    _git(path, "config", "user.email", "synthetic@example.invalid")
    runtime_source = (
        path / "src/research_machine/interfaces/runtime_promotion.py"
    )
    runtime_source.parent.mkdir(parents=True)
    runtime_source.write_text("# synthetic runtime-promotion fixture\n")
    _git(path, "add", str(runtime_source.relative_to(path)))
    _git(path, "commit", "--quiet", "-m", "Synthetic runtime fixture")
    return _git(path, "rev-parse", "HEAD")


def _workspace_snapshot(path: Path) -> dict[str, str]:
    return {
        str(item.relative_to(path)): _sha256(item)
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def _fixture(tmp_path: Path) -> tuple[dict, Path, Path]:
    runtime_repository = tmp_path / "candidate-runtime"
    runtime_revision = _clean_runtime_repository(runtime_repository)
    workspace_path = tmp_path / "workspace"
    service, hypothesis_id = prepared_service(workspace_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    output = artifacts / "proof-output.json"
    output.write_text('{"checker":"passed"}\n')
    output_sha256 = _sha256(output)
    record_path = tmp_path / "representative-run.json"
    record_sha256 = _write_json(record_path, {
        "protocol_id": protocol.protocol_id,
        "started_at": "2026-09-02T12:01:00Z",
        "completed_at": "2026-09-02T12:02:00Z",
        "analysis_code_hash": CODE_HASH,
        "environment_hash": ENVIRONMENT_HASH,
        "random_seed_reveal": SEED_REVEAL,
        "dataset_ids": [],
        "output_artifacts": [{
            "locator": output.name,
            "sha256": output_sha256,
            "size_bytes": output.stat().st_size,
            "media_type": "application/json",
        }],
        "quality_gates": [{
            "gate_id": "proof-check",
            "status": QualityGateStatus.PASSED.value,
            "summary": "Synthetic checker fixture result.",
            "required": True,
            "details": {"evidence_sha256": output_sha256},
        }],
        "summary": "Synthetic representative run for process testing.",
        "synthetic": False,
        "metadata": {
            "protocol_deviation_disclosure": {
                "status": "no_deviations_declared",
                "deviations": [],
            },
            "result_exposure_disclosure": {
                "status": "favorable_output_seen",
                "exposures": [{
                    "exposure_id": "synthetic-development-output",
                    "artifact_locator": output.name,
                    "artifact_sha256": output_sha256,
                    "seen_at": "2026-09-02T11:00:00Z",
                    "description": (
                        "Synthetic favorable output was seen before fixture "
                        "registration."
                    ),
                }],
            },
        },
    })
    ledger = service.verify_ledger("formal")
    audit = service.audit_rigor("formal", fail_on="never")
    manifest = {
        "schema_version": 1,
        "runtime_repository": str(runtime_repository.resolve()),
        "expected_runtime_revision": runtime_revision,
        "expected_runtime_clean": True,
        "workspace": {
            "path": str(workspace_path.resolve()),
            "inquiry_id": "formal",
            "expected_ledger_head_sha256": ledger["head_hash"],
            "expected_conclusion_ceiling": audit.conclusion_ceiling,
        },
        "representative_run": {
            "record_path": str(record_path.resolve()),
            "expected_record_sha256": record_sha256,
            "expected_preflight_status": "ready",
            "expected_record_status_if_submitted": "completed",
            "expected_effective_evidence_eligibility": False,
            "artifact_root": str(artifacts.resolve()),
        },
    }
    return manifest, workspace_path, runtime_repository


def _audit(tmp_path: Path, manifest: dict) -> dict:
    manifest_path = tmp_path / "promotion-manifest.json"
    manifest_sha256 = _write_json(manifest_path, manifest)
    return audit_runtime_promotion(
        manifest_path,
        expected_manifest_sha256=manifest_sha256,
        _runtime_source_path=(
            Path(manifest["runtime_repository"])
            / "src/research_machine/interfaces/runtime_promotion.py"
        ),
    )


def test_promotion_audit_passes_expected_ineligible_preflight_without_writes(
    tmp_path: Path,
) -> None:
    manifest, workspace, runtime = _fixture(tmp_path)
    workspace_before = _workspace_snapshot(workspace)
    runtime_before = _workspace_snapshot(runtime)

    report = _audit(tmp_path, manifest)

    assert report["status"] == "passed"
    assert report["manifest_expectations_met"] is True
    assert report["promotion_authorized"] is False
    assert report["target_workspace_modified"] is False
    assert report["scientific_validity_interpreted"] is False
    runtime_check = report["checks"]["runtime_revision_and_cleanliness"]
    assert runtime_check["status"] == "passed"
    assert runtime_check["runtime_source_path_matches"] is True
    assert runtime_check["runtime_source_tracked"] is True
    assert report["checks"]["workspace"]["status"] == "passed"
    run = report["checks"]["representative_run"]
    assert run["status"] == "passed"
    assert run["observed_effective_evidence_eligibility"] is False
    assert run["would_append_event"] is False
    assert report["checks"]["notebook_freeze_bundle"] == {
        "status": "not_requested"
    }
    assert _workspace_snapshot(workspace) == workspace_before
    assert _workspace_snapshot(runtime) == runtime_before
    assert _git(runtime, "status", "--porcelain") == ""


@pytest.mark.parametrize(
    ("mutation", "check_name"),
    [
        (
            lambda manifest: manifest.update(
                {"expected_runtime_revision": "0" * 40}
            ),
            "runtime_revision_and_cleanliness",
        ),
        (
            lambda manifest: manifest["workspace"].update(
                {"expected_ledger_head_sha256": "0" * 64}
            ),
            "workspace",
        ),
        (
            lambda manifest: manifest["workspace"].update(
                {"expected_conclusion_ceiling": "different process ceiling"}
            ),
            "workspace",
        ),
        (
            lambda manifest: manifest["representative_run"].update(
                {"expected_effective_evidence_eligibility": True}
            ),
            "representative_run",
        ),
    ],
)
def test_promotion_audit_fails_closed_on_expected_observation_mismatch(
    tmp_path: Path,
    mutation,
    check_name: str,
) -> None:
    manifest, _, _ = _fixture(tmp_path)
    mutation(manifest)

    report = _audit(tmp_path, manifest)

    assert report["status"] == "failed"
    assert report["manifest_expectations_met"] is False
    assert report["checks"][check_name]["status"] == "failed"


def test_promotion_audit_rejects_dirty_runtime(tmp_path: Path) -> None:
    manifest, _, runtime = _fixture(tmp_path)
    (runtime / "untracked.txt").write_text("uncommitted fixture state\n")

    report = _audit(tmp_path, manifest)

    check = report["checks"]["runtime_revision_and_cleanliness"]
    assert check["status"] == "failed"
    assert check["observed_clean"] is False
    assert check["dirty_entry_count"] == 1


def test_promotion_audit_rejects_another_loaded_runtime_source(
    tmp_path: Path,
) -> None:
    manifest, _, _ = _fixture(tmp_path)
    manifest_path = tmp_path / "promotion-manifest.json"
    manifest_sha256 = _write_json(manifest_path, manifest)
    other_source = tmp_path / "different-runtime" / "runtime_promotion.py"
    other_source.parent.mkdir()
    other_source.write_text("# wrong loaded runtime fixture\n")

    report = audit_runtime_promotion(
        manifest_path,
        expected_manifest_sha256=manifest_sha256,
        _runtime_source_path=other_source,
    )

    check = report["checks"]["runtime_revision_and_cleanliness"]
    assert check["status"] == "failed"
    assert check["observed_clean"] is True
    assert check["runtime_source_path_matches"] is False


def test_promotion_audit_does_not_preflight_changed_record_bytes(
    tmp_path: Path,
) -> None:
    manifest, _, _ = _fixture(tmp_path)
    record_path = Path(manifest["representative_run"]["record_path"])
    changed = json.loads(record_path.read_text())
    changed["summary"] = "Changed after the manifest was reviewed."
    _write_json(record_path, changed)

    report = _audit(tmp_path, manifest)

    check = report["checks"]["representative_run"]
    assert check["status"] == "failed"
    assert check["preflight_skipped"] is True
    assert check["observed_record_sha256"] != check["expected_record_sha256"]


def test_promotion_audit_replays_optional_bundle_and_detects_drift(
    tmp_path: Path,
) -> None:
    manifest, _, _ = _fixture(tmp_path)
    bundle_root = tmp_path / "bundle-inputs"
    bundle_root.mkdir()
    notebook, dependencies, static_receipt, runtime_receipt, _ = _bundle_inputs(
        bundle_root
    )
    bundle_path = bundle_root / "freeze-input-bundle.json"
    create_notebook_freeze_input_bundle(
        notebook,
        dependencies,
        runtime_receipt,
        bundle_path,
        workspace_root=bundle_root,
        static_preflight_receipt_path=static_receipt,
    )
    manifest["notebook_freeze_bundle"] = {
        "path": str(bundle_path.resolve()),
        "expected_sha256": _sha256(bundle_path),
    }

    passed = _audit(tmp_path, manifest)
    assert passed["checks"]["notebook_freeze_bundle"]["status"] == "passed"
    assert passed["checks"]["notebook_freeze_bundle"]["dependency_count"] == 1

    (bundle_root / "registered-specification.json").write_text("drift\n")
    failed = _audit(tmp_path, manifest)
    assert failed["manifest_expectations_met"] is False
    bundle_check = failed["checks"]["notebook_freeze_bundle"]
    assert bundle_check["status"] == "failed"
    assert "dependency replay failed" in bundle_check["error"]


def test_promotion_manifest_hash_and_clean_expectation_are_fail_closed(
    tmp_path: Path,
) -> None:
    manifest, _, _ = _fixture(tmp_path)
    manifest_path = tmp_path / "promotion-manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="manifest hash mismatch"):
        audit_runtime_promotion(
            manifest_path,
            expected_manifest_sha256="0" * 64,
        )

    manifest["expected_runtime_clean"] = False
    manifest_sha256 = _write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="must be true"):
        audit_runtime_promotion(
            manifest_path,
            expected_manifest_sha256=manifest_sha256,
        )


def test_promotion_cli_exit_codes_distinguish_failed_audit_and_input_error(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _, runtime = _fixture(tmp_path)
    runtime_source = (
        runtime / "src/research_machine/interfaces/runtime_promotion.py"
    )
    monkeypatch.setattr(
        "research_machine.interfaces.runtime_promotion._current_runtime_source",
        lambda: runtime_source,
    )
    manifest_path = tmp_path / "promotion-manifest.json"
    manifest_sha256 = _write_json(manifest_path, manifest)
    arguments = [
        "--json",
        "runtime-promotion",
        "audit",
        "--manifest",
        str(manifest_path),
        "--expect-manifest-sha256",
        manifest_sha256,
    ]
    assert main(arguments) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["manifest_expectations_met"] is True
    assert result["promotion_authorized"] is False

    manifest["expected_runtime_revision"] = "0" * 40
    manifest_sha256 = _write_json(manifest_path, manifest)
    arguments[-1] = manifest_sha256
    assert main(arguments) == 1
    assert json.loads(capsys.readouterr().out)["result"]["status"] == "failed"

    assert main([*arguments[:-1], "0" * 64]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["ok"] is False
