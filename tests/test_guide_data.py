"""G05 read-only CSV inventory and explicit synthetic dataset handoff."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import CreateInquiry, RegisterDataset
from research_machine.application.guide import preview_csv_data
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import DatasetArtifact, DatasetRole
from research_machine.interfaces.cli import main


DATA = Path(__file__).parent / "fixtures" / "guide" / "independent-two-group.csv"


def _spec() -> dict:
    return {
        "method": "independent_mean_difference_ci",
        "study_design": "independent_groups",
        "unit_column": "unit",
        "group_column": "group",
        "outcome_column": "outcome",
        "groups": ["treatment", "control"],
        "measurement_definitions": [{
            "measurement_id": "synthetic-outcome-v1",
            "data_column": "outcome",
            "scale_type": "interval",
            "unit": "synthetic points",
            "admissible_values": [],
            "missing_value_codes": ["<blank>"],
            "valid_min": 0.0,
            "valid_max": 100.0,
        }],
    }


def test_csv_preview_preserves_bytes_and_keeps_custody_gap(tmp_path: Path, capsys) -> None:
    before_bytes = DATA.read_bytes()
    expected_hash = hashlib.sha256(before_bytes).hexdigest()
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(_spec()), encoding="utf-8")
    workspace = tmp_path / "workspace"
    assert main([
        "--workspace", str(workspace), "--json", "guide", "data",
        "--file", str(DATA), "--spec-file", str(spec_file),
        "--expect-sha256", expected_hash,
    ]) == 0
    preview = json.loads(capsys.readouterr().out)["result"]
    assert preview["raw_sha256"] == expected_hash
    assert preview["raw_size_bytes"] == len(before_bytes)
    assert preview["row_count"] == 4
    assert preview["unit_count"] == 4
    assert preview["quality_issues"] == []
    outcome = next(item for item in preview["columns"] if item["name"] == "outcome")
    assert outcome["role"] == "primary_outcome"
    assert outcome["scale_type"] == "interval"
    assert outcome["observed_count"] == 4
    assert outcome["missing_count"] == 0
    assert preview["role"] == "unregistered_input"
    assert "measurement_custody_unverified" in preview["readiness_gaps"]
    assert preview["scientific_evidence_eligible"] is False
    assert preview["canonical_write_performed"] is False
    assert DATA.read_bytes() == before_bytes
    assert not workspace.exists()

    # Registration is a separate canonical operation. Synthetic registration
    # retains the byte identity but cannot manufacture real source custody.
    service = ResearchService(FileSystemRepository(workspace), actor="guide-fixture")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Synthetic data handoff", "Could the groups differ?"))
    service.register_dataset(RegisterDataset(
        dataset_id="guide-synthetic-data-v1",
        name="Fabricated four-row CSV",
        role=DatasetRole.EXPLORATORY,
        artifacts=[DatasetArtifact(
            "independent-two-group.csv", expected_hash, len(before_bytes), "text/csv"
        )],
        observation_unit="independent fabricated unit",
        synthetic=True,
    ))
    inventory = service.dataset_inventory()
    entry = inventory["datasets"][0]
    assert entry["role"] == "exploratory"
    assert entry["observation_access"]["status"] == "synthetic_fixture"
    assert entry["measurement_custody"]["service_verified"] is False
    assert entry["payload_commitment"]["sealed"] is True
    assert service.verify_ledger()["valid"] is True


def test_csv_preview_reports_duplicate_invalid_missing_and_changed_bytes(tmp_path: Path) -> None:
    original = DATA.read_bytes()
    spec = _spec()
    bad = tmp_path / "bad.csv"
    bad.write_bytes(original.replace(b"u04,treatment,6", b"u01,treatment,bogus"))
    report = preview_csv_data(bad, spec)
    assert report["unit_count"] == 3
    assert "repeated independent-unit identifiers" in report["quality_issues"]
    assert any("non-numeric value" in issue for issue in report["quality_issues"])
    assert "data_quality_issues" in report["readiness_gaps"]
    assert report["scientific_evidence_eligible"] is False

    missing = tmp_path / "missing.csv"
    missing.write_bytes(original.replace(b"u04,treatment,6", b"u04,treatment,"))
    missing_report = preview_csv_data(missing, spec)
    outcome = next(item for item in missing_report["columns"] if item["name"] == "outcome")
    assert outcome["missing_count"] == 1
    assert outcome["observed_count"] == 3
    assert missing_report["scientific_evidence_eligible"] is False

    with pytest.raises(ValidationError, match="do not match expected SHA-256"):
        preview_csv_data(bad, spec, expected_sha256=hashlib.sha256(original).hexdigest())
