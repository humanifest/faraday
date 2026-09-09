from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.measurement.preprocessing import (
    assess_preprocessing_conformance,
    verify_preprocessing_conformance_record,
)


def _pipeline(
    *,
    pipeline_id: str = "registered-pipeline",
    smoothing_window: int = 5,
    extra_step: bool = False,
) -> dict:
    steps = [
        {
            "step_id": "load-raw",
            "operation": "read fixture bytes",
            "parameters": {"encoding": "utf-8"},
            "input_artifacts": [{
                "artifact_id": "raw-input",
                "sha256": "1" * 64,
                "media_type": "text/csv",
                "role": "raw observation fixture",
            }],
            "output_artifacts": [{
                "artifact_id": "loaded-table",
                "sha256": "2" * 64,
                "media_type": "application/json",
                "role": "loaded table fixture",
            }],
            "implementation_sha256": "3" * 64,
        },
        {
            "step_id": "smooth-signal",
            "operation": "moving average",
            "parameters": {"window": smoothing_window, "edge_policy": "drop"},
            "input_artifacts": [{
                "artifact_id": "loaded-table",
                "sha256": "2" * 64,
                "media_type": "application/json",
                "role": "loaded table fixture",
            }],
            "output_artifacts": [{
                "artifact_id": "smoothed-table",
                "sha256": "4" * 64,
                "media_type": "application/json",
                "role": "preprocessed table fixture",
            }],
            "implementation_sha256": "5" * 64,
        },
    ]
    if extra_step:
        steps.append({
            "step_id": "posthoc-filter",
            "operation": "discard rows after result inspection",
            "parameters": {"threshold": 0.01},
            "input_artifacts": [{
                "artifact_id": "smoothed-table",
                "sha256": "4" * 64,
                "media_type": "application/json",
                "role": "preprocessed table fixture",
            }],
            "output_artifacts": [{
                "artifact_id": "filtered-table",
                "sha256": "6" * 64,
                "media_type": "application/json",
                "role": "posthoc filtered fixture",
            }],
            "implementation_sha256": "7" * 64,
        })
    return {
        "pipeline_id": pipeline_id,
        "purpose": "Synthetic fixture for preprocessing conformance.",
        "steps": steps,
    }


def _write_json(path: Path, value: dict) -> str:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_preprocessing_conformance_passes_for_exact_registered_pipeline(
    tmp_path: Path, capsys
) -> None:
    registered = tmp_path / "registered-pipeline.json"
    observed = tmp_path / "observed-pipeline.json"
    registered_sha = _write_json(registered, _pipeline())
    observed_sha = _write_json(observed, _pipeline())
    output = tmp_path / "preprocessing-conformance"
    assert main([
        "--json", "measurement", "assess-preprocessing",
        "--registered-pipeline-file", str(registered),
        "--expected-registered-pipeline-sha256", registered_sha,
        "--observed-pipeline-file", str(observed),
        "--expected-observed-pipeline-sha256", observed_sha,
        "--output", str(output),
    ]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "preprocessing_conformance_passed"
    record = json.loads(Path(result["path"], "preprocessing-conformance.json").read_text())
    assert record["registered_pipeline"]["sha256"] == registered_sha
    assert record["observed_pipeline"]["sha256"] == observed_sha
    assert record["registered_pipeline_snapshot"] == _pipeline()
    assert record["observed_pipeline_snapshot"] == _pipeline()
    assert record["step_results"] == [
        {"step_id": "load-raw", "status": "passed", "differences": []},
        {"step_id": "smooth-signal", "status": "passed", "differences": []},
    ]
    assert record["findings"] == []
    assert record["scientific_evidence_eligible"] is False
    assert record["authorized_actions"] == []


def test_preprocessing_conformance_fails_when_parameters_change(tmp_path: Path) -> None:
    registered = tmp_path / "registered-pipeline.json"
    observed = tmp_path / "observed-pipeline.json"
    registered_sha = _write_json(registered, _pipeline())
    observed_sha = _write_json(observed, _pipeline(smoothing_window=9))
    result = assess_preprocessing_conformance(
        registered,
        registered_sha,
        observed,
        observed_sha,
        tmp_path / "preprocessing-conformance",
    )
    record = json.loads(Path(result["path"], "preprocessing-conformance.json").read_text())
    assert result["status"] == "preprocessing_conformance_failed"
    assert "STEP_PARAMETERS_MISMATCH" in {finding["code"] for finding in record["findings"]}
    assert record["step_results"][1] == {
        "step_id": "smooth-signal",
        "status": "failed",
        "differences": ["parameters"],
    }
    assert record["scientific_evidence_eligible"] is False


def test_preprocessing_conformance_fails_for_reordered_or_extra_steps(tmp_path: Path) -> None:
    registered_pipeline = _pipeline()
    observed_pipeline = _pipeline(extra_step=True)
    observed_pipeline["steps"] = [
        observed_pipeline["steps"][1],
        observed_pipeline["steps"][0],
        observed_pipeline["steps"][2],
    ]
    registered = tmp_path / "registered-pipeline.json"
    observed = tmp_path / "observed-pipeline.json"
    registered_sha = _write_json(registered, registered_pipeline)
    observed_sha = _write_json(observed, observed_pipeline)
    result = assess_preprocessing_conformance(
        registered,
        registered_sha,
        observed,
        observed_sha,
        tmp_path / "preprocessing-conformance",
    )
    record = json.loads(Path(result["path"], "preprocessing-conformance.json").read_text())
    codes = {finding["code"] for finding in record["findings"]}
    assert result["status"] == "preprocessing_conformance_failed"
    assert "STEP_ORDER_MISMATCH" in codes
    assert "STEP_EXTRA" in codes
    assert record["observed_pipeline"]["step_ids"] == [
        "smooth-signal", "load-raw", "posthoc-filter",
    ]
    assert record["scientific_evidence_eligible"] is False


def test_preprocessing_conformance_rejects_untrusted_registered_hash(
    tmp_path: Path,
) -> None:
    registered = tmp_path / "registered-pipeline.json"
    observed = tmp_path / "observed-pipeline.json"
    _write_json(registered, _pipeline())
    observed_sha = _write_json(observed, _pipeline())
    output = tmp_path / "preprocessing-conformance"
    with pytest.raises(ValidationError, match="expected_registered_pipeline_sha256"):
        assess_preprocessing_conformance(
            registered,
            "0" * 64,
            observed,
            observed_sha,
            output,
        )
    assert not output.exists()


def test_preprocessing_conformance_record_verifier_replays_current_bytes(
    tmp_path: Path,
) -> None:
    registered = tmp_path / "registered-pipeline.json"
    observed = tmp_path / "observed-pipeline.json"
    registered_sha = _write_json(registered, _pipeline())
    observed_sha = _write_json(observed, _pipeline())
    result = assess_preprocessing_conformance(
        registered,
        registered_sha,
        observed,
        observed_sha,
        tmp_path / "preprocessing-conformance",
    )
    record = Path(result["path"]) / "preprocessing-conformance.json"

    verified = verify_preprocessing_conformance_record(
        record,
        result["assessment_sha256"],
        expected_registered_pipeline_sha256=registered_sha,
        expected_observed_pipeline_sha256=observed_sha,
    )

    assert verified["record_status"] == "preprocessing_conformance_passed"
    assert verified["registered_pipeline_sha256"] == registered_sha
    assert verified["observed_pipeline_sha256"] == observed_sha
    assert verified["comparison_replay"] == "verified"
    assert verified["scientific_evidence_eligible"] is False


def test_preprocessing_conformance_record_replays_retained_comparison(
    tmp_path: Path,
) -> None:
    registered = tmp_path / "registered-pipeline.json"
    observed = tmp_path / "observed-pipeline.json"
    registered_sha = _write_json(registered, _pipeline())
    observed_sha = _write_json(observed, _pipeline(smoothing_window=9))
    result = assess_preprocessing_conformance(
        registered,
        registered_sha,
        observed,
        observed_sha,
        tmp_path / "preprocessing-conformance",
    )
    record = Path(result["path"]) / "preprocessing-conformance.json"
    retained = json.loads(record.read_text())
    retained["step_results"][1]["differences"] = ["implementation_sha256"]
    tampered_sha = _write_json(record, retained)

    with pytest.raises(ValidationError, match="retained pipeline comparison"):
        verify_preprocessing_conformance_record(record, tampered_sha)


def test_preprocessing_conformance_record_labels_legacy_missing_snapshots(
    tmp_path: Path,
) -> None:
    registered = tmp_path / "registered-pipeline.json"
    observed = tmp_path / "observed-pipeline.json"
    registered_sha = _write_json(registered, _pipeline())
    observed_sha = _write_json(observed, _pipeline())
    result = assess_preprocessing_conformance(
        registered,
        registered_sha,
        observed,
        observed_sha,
        tmp_path / "preprocessing-conformance",
    )
    record = Path(result["path"]) / "preprocessing-conformance.json"
    retained = json.loads(record.read_text())
    del retained["registered_pipeline_snapshot"]
    del retained["observed_pipeline_snapshot"]
    legacy_sha = _write_json(record, retained)

    verified = verify_preprocessing_conformance_record(record, legacy_sha)

    assert verified["comparison_replay"] == "legacy_missing"


def test_preprocessing_conformance_record_requires_findings_for_failed_steps(
    tmp_path: Path,
) -> None:
    registered = tmp_path / "registered-pipeline.json"
    observed = tmp_path / "observed-pipeline.json"
    registered_sha = _write_json(registered, _pipeline())
    observed_sha = _write_json(observed, _pipeline(smoothing_window=9))
    result = assess_preprocessing_conformance(
        registered,
        registered_sha,
        observed,
        observed_sha,
        tmp_path / "preprocessing-conformance",
    )
    record = Path(result["path"]) / "preprocessing-conformance.json"
    retained = json.loads(record.read_text())
    del retained["registered_pipeline_snapshot"]
    del retained["observed_pipeline_snapshot"]
    retained["findings"] = [
        {
            "severity": "error",
            "code": "STEP_PARAMETERS_MISMATCH",
            "message": "A preprocessing step changed without retained step scope.",
        }
    ]
    trusted_sha = _write_json(record, retained)

    with pytest.raises(ValidationError, match="failed steps: smooth-signal"):
        verify_preprocessing_conformance_record(record, trusted_sha)


def test_preprocessing_conformance_record_verifier_rejects_evidence_upgrade(
    tmp_path: Path,
) -> None:
    registered = tmp_path / "registered-pipeline.json"
    observed = tmp_path / "observed-pipeline.json"
    registered_sha = _write_json(registered, _pipeline())
    observed_sha = _write_json(observed, _pipeline())
    result = assess_preprocessing_conformance(
        registered,
        registered_sha,
        observed,
        observed_sha,
        tmp_path / "preprocessing-conformance",
    )
    record = Path(result["path"]) / "preprocessing-conformance.json"
    retained = json.loads(record.read_text())
    retained["scientific_evidence_eligible"] = True
    tampered_sha = _write_json(record, retained)

    with pytest.raises(ValidationError, match="must remain non-evidentiary"):
        verify_preprocessing_conformance_record(record, tampered_sha)


def test_preprocessing_conformance_record_replays_conclusion_ceiling(
    tmp_path: Path,
) -> None:
    registered = tmp_path / "registered-pipeline.json"
    observed = tmp_path / "observed-pipeline.json"
    registered_sha = _write_json(registered, _pipeline())
    observed_sha = _write_json(observed, _pipeline())
    result = assess_preprocessing_conformance(
        registered,
        registered_sha,
        observed,
        observed_sha,
        tmp_path / "preprocessing-conformance",
    )
    record = Path(result["path"]) / "preprocessing-conformance.json"
    retained = json.loads(record.read_text())
    retained["conclusion_ceiling"] = (
        "This preprocessing record proves implementation correctness."
    )
    tampered_sha = _write_json(record, retained)

    with pytest.raises(ValidationError, match="conclusion ceiling has changed"):
        verify_preprocessing_conformance_record(record, tampered_sha)
