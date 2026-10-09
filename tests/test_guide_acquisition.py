"""C05 acquisition previews reuse connector and instrument byte receipts."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from research_machine.addons.connector import fetch_source_proposal, write_source_proposal
from research_machine.addons.models import AddonManifest, InstrumentAdapter, ScientificConnector
from research_machine.application.guide_acquisition import preview_guide_acquisition
from research_machine.domain.errors import ValidationError
from research_machine.measurement.instrument import inspect_instrument_source


RIGHTS = {
    "source_owner": "Synthetic fixture owner",
    "rights_basis": "Fabricated bytes for local tests",
    "consent_basis": "No participants in this fixture",
    "review_state": "claimed_permitted",
}


def _connector_fetch(query):
    return {"bytes": b"fabricated-source-v1", "metadata": {"record_id": query["record_id"]}}


def _instrument_inspect(source_bytes, config):
    assert source_bytes == b"fabricated-capture-v1"
    return {
        "captured_at": config["captured_at"],
        "captured_at_basis": "user_supplied",
        "acquisition_method": "synthetic_fixture",
        "instrument_identifier": "fixture-01",
        "instrument_model": "FixtureScope",
        "native_metadata": {},
        "warnings": [],
    }


def test_connector_handoff_preserves_bytes_and_rights_ceiling(tmp_path: Path) -> None:
    connector = ScientificConnector(
        "guide-fixture", "Guide fixture", "Synthetic source bytes.",
        ("scientific_connector",), ("record_id",), _connector_fetch,
    )
    manifest = AddonManifest(
        "guide_connector_fixture", "Guide connector fixture", "1", "test",
        "Synthetic only", connectors=(connector,),
    )
    proposal = fetch_source_proposal(manifest, connector, {"record_id": "r1"})
    output = write_source_proposal(proposal, tmp_path / "connector")
    receipt = Path(output["receipt"])
    digest = hashlib.sha256(receipt.read_bytes()).hexdigest()
    preview = preview_guide_acquisition(
        source_kind="connector", receipt_file=receipt,
        expected_receipt_sha256=digest, rights=RIGHTS,
        connector=connector, manifest=manifest,
    )
    assert preview["status"] == "review_only_source_handoff"
    assert preview["raw_source_sha256"] == hashlib.sha256(b"fabricated-source-v1").hexdigest()
    assert preview["receipt_sha256"] == digest
    assert preview["implementation_replayed"] is True
    assert preview["timing"]["status"] == "unverified"
    assert preview["rights_verified"] is False
    assert preview["consent_verified"] is False
    assert preview["custody_cleared"] is False
    assert preview["acquisition_authorized"] is False
    assert preview["scientific_evidence_eligible"] is False

    denied = preview_guide_acquisition(
        source_kind="connector", receipt_file=receipt,
        expected_receipt_sha256=digest,
        rights={**RIGHTS, "review_state": "denied"},
        connector=connector, manifest=manifest,
    )
    assert denied["status"] == "blocked" and denied["blocking_issues"]
    Path(output["source"]).write_bytes(b"changed")
    with pytest.raises(ValidationError, match="source bytes do not match"):
        preview_guide_acquisition(
            source_kind="connector", receipt_file=receipt,
            expected_receipt_sha256=digest, rights=RIGHTS,
            connector=connector, manifest=manifest,
        )


def test_failed_instrument_calibration_blocks_handoff(tmp_path: Path) -> None:
    source = tmp_path / "capture.bin"
    source.write_bytes(b"fabricated-capture-v1")
    adapter = InstrumentAdapter(
        "guide-instrument-fixture", "Guide instrument fixture", "Synthetic capture.",
        ("application/octet-stream",), ("captured_at",), _instrument_inspect,
    )
    manifest = AddonManifest(
        "guide_instrument_fixture", "Guide instrument fixture", "1", "test",
        "Synthetic only", instrument_adapters=(adapter,),
    )
    config = {"captured_at": "2026-10-08T12:00:00Z"}
    inspection = inspect_instrument_source(
        manifest, adapter, source, "application/octet-stream", config,
        tmp_path / "inspection",
    )
    record = Path(inspection["path"]) / "instrument-inspection.json"
    record_sha = hashlib.sha256(record.read_bytes()).hexdigest()
    raw_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    calibration = {
        "check_id": "calibration-fixture-v1", "status": "failed",
        "diagnostic": "Reference check exceeded the declared tolerance.",
        "source_sha256": raw_sha,
    }
    preview = preview_guide_acquisition(
        source_kind="instrument", receipt_file=record,
        expected_receipt_sha256=record_sha, source_file=source,
        rights=RIGHTS, calibration=calibration,
    )
    assert preview["status"] == "blocked"
    assert "instrument calibration failed" in preview["blocking_issues"]
    assert preview["timing"]["captured_at"] == config["captured_at"]
    assert preview["timing"]["basis"] == "user_supplied"
    assert preview["raw_source_sha256"] == raw_sha
    assert preview["calibration"]["source_sha256"] == raw_sha
    assert preview["calibration"]["verified"] is False
    assert preview["custody_cleared"] is False
    assert preview["acquisition_authorized"] is False

    with pytest.raises(ValidationError, match="different source bytes"):
        preview_guide_acquisition(
            source_kind="instrument", receipt_file=record,
            expected_receipt_sha256=record_sha, source_file=source,
            rights=RIGHTS, calibration={**calibration, "source_sha256": "0" * 64},
        )
    source.write_bytes(b"changed")
    with pytest.raises(ValidationError, match="source SHA-256 mismatch"):
        preview_guide_acquisition(
            source_kind="instrument", receipt_file=record,
            expected_receipt_sha256=record_sha, source_file=source,
            rights=RIGHTS, calibration=calibration,
        )
