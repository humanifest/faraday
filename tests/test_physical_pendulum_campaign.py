from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import pytest

from campaigns.newtonian_pendulum.physical.executor import (
    analyze_field_run,
    write_analysis_package,
)
from campaigns.newtonian_pendulum.physical.prepare import prepare_field_workspace
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import RecordRun, RegisterDataset
from research_machine.application.service import ResearchService
from research_machine.domain.models import (
    DatasetArtifact,
    DatasetRole,
    QualityGateResult,
)


FROZEN_AT = "2026-09-04T12:00:00Z"


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _fill_kit(output_root: Path, model: str, *, angle_deg: float = 5.0) -> Path:
    kit = output_root / "collection-kit"
    observations_path = kit / "observations.csv"
    with observations_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for row in rows:
        length = float(row["length_target_m"])
        if model in {"square_root", "square_root_wrong_scale"}:
            gravity = 9.80665 if model == "square_root" else 8.5
            period = 2 * math.pi * math.sqrt(length / gravity)
        elif model == "linear":
            period = 1.75 * length
        else:
            period = 1.25
        sequence = int(row["sequence"])
        noise = ((sequence % 5) - 2) * 0.0004
        period += noise
        start = sequence * 100.0
        row.update(
            {
                "length_measured_m": f"{length:.6f}",
                "angle_start_deg": f"{angle_deg:.3f}",
                "start_time_s": f"{start:.9f}",
                "end_time_s": f"{start + period * 20:.9f}",
                "amplitude_end_deg": f"{angle_deg * 0.9:.3f}",
            }
        )
        if row["timing_audit"] == "yes":
            row["audit_start_time_s"] = f"{start + 0.01:.9f}"
            row["audit_end_time_s"] = f"{start + period * 20 + 0.01:.9f}"
    _write_csv(observations_path, fields, rows)

    clock_path = kit / "clock-calibration.csv"
    with clock_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        clock_fields = list(reader.fieldnames or [])
        clock_rows = list(reader)
    for index, row in enumerate(clock_rows):
        row["observed_duration_s"] = "60.000"
        row["performed_at_utc"] = f"2026-09-04T12:{index + 1:02d}:00Z"
    _write_csv(clock_path, clock_fields, clock_rows)

    raw_root = kit / "raw"
    raw_root.mkdir()
    source_rows: list[dict[str, object]] = []
    for block in range(1, 9):
        source = raw_root / f"block-{block:02d}.dat"
        source.write_bytes(f"test raw source for block {block}\n".encode())
        source_rows.append(
            {
                "source_id": f"block-{block:02d}",
                "block": block,
                "locator": f"raw/{source.name}",
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "size_bytes": source.stat().st_size,
            }
        )
    _write_csv(
        kit / "source-files.csv",
        ["source_id", "block", "locator", "sha256", "size_bytes"],
        source_rows,
    )

    session_path = kit / "session.json"
    session = json.loads(session_path.read_text(encoding="utf-8"))
    session.update(
        {
            "collection_started_at_utc": "2026-09-04T12:01:00Z",
            "collection_completed_at_utc": "2026-09-04T13:01:00Z",
            "analysis_completed_at_utc": "2026-09-04T13:05:00Z",
            "collector_id": "test-collector",
            "location_description": "test fixture only",
            "apparatus_id": "test-apparatus",
        }
    )
    session_path.write_text(
        json.dumps(session, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return kit


def _gate_statuses(report: dict[str, object]) -> dict[str, str]:
    gates = report["quality_gates"]
    assert isinstance(gates, list)
    return {
        str(gate["gate_id"]): str(gate["status"])
        for gate in gates
        if isinstance(gate, dict)
    }


def _artifact(path: Path) -> DatasetArtifact:
    return DatasetArtifact(
        locator=str(path.resolve()),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size_bytes=path.stat().st_size,
    )


def _prepare(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    output = tmp_path / "physical"
    summary = prepare_field_workspace(
        output,
        human_reviewed=True,
        clock=lambda: FROZEN_AT,
    )
    return output, summary


def test_prepare_freezes_complete_protocol_before_any_observations(
    tmp_path: Path,
) -> None:
    output, summary = _prepare(tmp_path)
    service = ResearchService(FileSystemRepository(output / ".research"))
    state = service.show_inquiry()
    protocol = state["protocols"][0]

    assert summary["ready_for_collection"] is True
    assert summary["observations_present_at_freeze"] is False
    assert summary["dataset_count"] == 0
    assert summary["run_count"] == 0
    assert protocol["status"] == "frozen"
    assert protocol["protocol_kind"] == "experimental"
    assert protocol["analysis_mode"] == "confirmatory"
    assert len(protocol["measurement_definitions"]) == 8
    assert len(state["datasets"]) == 0
    assert len(state["runs"]) == 0
    assert summary["ledger_verification"]["valid"] is True

    with (output / "collection-kit" / "schedule.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        schedule = list(csv.DictReader(handle))
    assert len(schedule) == 48
    for block in range(1, 9):
        lengths = {
            row["length_target_m"]
            for row in schedule
            if int(row["block"]) == block
        }
        assert lengths == {"0.200", "0.350", "0.500", "0.750", "1.000", "1.250"}


def test_physical_executor_recovers_square_root_with_valid_quality(
    tmp_path: Path,
) -> None:
    output, _ = _prepare(tmp_path)
    kit = _fill_kit(output, "square_root")

    report = analyze_field_run(kit)

    assert report["execution_quality_valid"] is True
    assert set(_gate_statuses(report).values()) == {"passed"}
    assert report["scientific_outcome"]["direction"] == "supports_square_root"
    assert report["primary_analysis"]["selected_model"] == "square_root"
    assert report["independent_analysis"]["selected_model"] == "square_root"
    assert report["scientific_outcome"]["claim_ceiling"].endswith(
        "does not validate a universal theory or establish a mechanism."
    )


def test_non_newtonian_outcome_does_not_fail_execution_quality(tmp_path: Path) -> None:
    output, summary = _prepare(tmp_path)
    kit = _fill_kit(output, "linear")

    package = write_analysis_package(
        kit,
        str(summary["dataset_id_reserved"]),
        output / "analysis",
    )
    record = json.loads(
        (output / "analysis" / "run-record.json").read_text(encoding="utf-8")
    )

    assert package["execution_quality_valid"] is True
    assert package["scientific_outcome"]["direction"] == "supports_linear"
    assert set(_gate_statuses(record).values()) == {"passed"}
    assert record["synthetic"] is False
    assert record["output_artifacts"][0]["locator"] == "analysis-report.json"
    assert record["metadata"]["scientific_outcome"]["direction"] == "supports_linear"


def test_generated_record_passes_core_preflight_without_becoming_real_evidence(
    tmp_path: Path,
) -> None:
    output, summary = _prepare(tmp_path)
    kit = _fill_kit(output, "square_root")
    service = ResearchService(
        FileSystemRepository(output / ".research"), actor="test-preflight"
    )
    input_paths = [
        kit / "observations.csv",
        kit / "clock-calibration.csv",
        kit / "source-files.csv",
        kit / "session.json",
        kit / "schedule.csv",
        kit / "protocol-summary.json",
        *sorted((kit / "raw").glob("*")),
    ]
    dataset = service.register_dataset(
        RegisterDataset(
            dataset_id=str(summary["dataset_id_reserved"]),
            name="Synthetic test fixture presented to physical preflight",
            role=DatasetRole.CONFIRMATORY,
            protocol_id=str(summary["protocol_id"]),
            artifacts=[_artifact(path) for path in input_paths],
            synthetic=True,
        )
    )
    write_analysis_package(kit, dataset.dataset_id, output / "analysis")
    value = json.loads(
        (output / "analysis" / "run-record.json").read_text(encoding="utf-8")
    )
    command = RecordRun(
        run_id=value["run_id"],
        protocol_id=value["protocol_id"],
        started_at=value["started_at"],
        completed_at=value["completed_at"],
        analysis_code_hash=value["analysis_code_hash"],
        environment_hash=value["environment_hash"],
        random_seed_reveal=value["random_seed_reveal"],
        dataset_ids=value["dataset_ids"],
        output_artifacts=[
            DatasetArtifact.from_dict(item) for item in value["output_artifacts"]
        ],
        quality_gates=[
            QualityGateResult.from_dict(item) for item in value["quality_gates"]
        ],
        summary=value["summary"],
        synthetic=value["synthetic"],
        metadata=value["metadata"],
        artifact_root=str(output / "analysis"),
    )

    preflight = service.preflight_run(command)

    assert preflight.status == "ready"
    assert preflight.exact_quality_gate_set is True
    assert preflight.quality_gate_order_matches_protocol is True
    assert preflight.artifact_integrity["status"] == "passed"
    assert preflight.scientific_evidence_eligible_if_submitted is False
    assert preflight.synthetic_if_submitted is True


def test_boundary_violation_withholds_scientific_interpretation(tmp_path: Path) -> None:
    output, _ = _prepare(tmp_path)
    kit = _fill_kit(output, "square_root", angle_deg=9.0)

    report = analyze_field_run(kit)

    assert report["execution_quality_valid"] is False
    assert _gate_statuses(report)["small-angle-boundary"] == "failed"
    assert report["scientific_outcome"]["direction"] == "not_interpretable"


def test_square_root_shape_without_registered_scale_is_inconclusive(
    tmp_path: Path,
) -> None:
    output, _ = _prepare(tmp_path)
    kit = _fill_kit(output, "square_root_wrong_scale")

    report = analyze_field_run(kit)

    assert report["execution_quality_valid"] is True
    assert report["primary_analysis"]["selected_model"] == "square_root"
    assert report["independent_analysis"]["selected_model"] == "square_root"
    assert report["scientific_outcome"]["direction"] == "inconclusive"


def test_raw_source_tampering_invalidates_execution(tmp_path: Path) -> None:
    output, _ = _prepare(tmp_path)
    kit = _fill_kit(output, "square_root")
    (kit / "raw" / "block-01.dat").write_bytes(b"changed after hashing\n")

    report = analyze_field_run(kit)

    assert report["execution_quality_valid"] is False
    assert _gate_statuses(report)["raw-source-integrity"] == "failed"
    assert report["scientific_outcome"]["direction"] == "not_interpretable"


def test_physical_protocol_requires_explicit_human_review(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit human review"):
        prepare_field_workspace(tmp_path / "unreviewed")

    assert not (tmp_path / "unreviewed").exists()
