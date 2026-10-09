"""Read-only guide view over existing low-authority acquisition receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from research_machine.addons.connector import verify_source_proposal
from research_machine.addons.models import AddonManifest, ScientificConnector
from research_machine.domain.errors import ValidationError
from research_machine.measurement.instrument import verify_instrument_inspection_record


def _canonical(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValidationError(f"guide acquisition {label} must be canonical non-blank text")
    return value


def preview_guide_acquisition(
    *, source_kind: str, receipt_file: Path, expected_receipt_sha256: str,
    rights: dict[str, Any], source_file: Path | None = None,
    connector: ScientificConnector | None = None,
    manifest: AddonManifest | None = None,
    calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Preserve acquisition identity and failures without granting custody."""
    if source_kind not in {"connector", "instrument"}:
        raise ValidationError("guide acquisition source_kind is unsupported")
    if not isinstance(rights, dict) or set(rights) != {
        "source_owner", "rights_basis", "consent_basis", "review_state",
    }:
        raise ValidationError("guide acquisition rights declaration fields are invalid")
    for field in ("source_owner", "rights_basis", "consent_basis"):
        _canonical(rights[field], field)
    if rights["review_state"] not in {"unverified", "denied", "claimed_permitted"}:
        raise ValidationError("guide acquisition rights review_state is unsupported")
    if source_kind == "connector":
        if source_file is not None or calibration is not None:
            raise ValidationError("guide connector preview cannot import instrument source or calibration")
        verified = verify_source_proposal(
            receipt_file, connector=connector, manifest=manifest,
            expected_receipt_sha256=expected_receipt_sha256,
        )
        raw_sha256 = verified["source_sha256"]
        timing = {"captured_at": None, "basis": None, "status": "unverified"}
        calibration_view = {"status": "not_applicable", "verified": False}
        source_receipt_replay = verified["implementation_replayed"]
    else:
        if connector is not None or manifest is not None or source_file is None:
            raise ValidationError("guide instrument preview requires its source file only")
        if source_file.is_symlink() or not source_file.is_file():
            raise ValidationError("guide instrument source must be a regular file")
        if source_file.stat().st_size > 16 * 1024 * 1024:
            raise ValidationError("guide instrument source exceeds the preview limit")
        raw_bytes = source_file.read_bytes()
        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        verified = verify_instrument_inspection_record(
            receipt_file, expected_receipt_sha256,
            expected_source_sha256=raw_sha256,
        )
        retained = receipt_file.read_bytes()
        if hashlib.sha256(retained).hexdigest() != verified["record_sha256"]:
            raise ValidationError("guide instrument receipt changed during replay")
        if source_file.is_symlink() or source_file.read_bytes() != raw_bytes:
            raise ValidationError("guide instrument source changed during preview")
        record = json.loads(retained)
        timing = {
            "captured_at": record["proposed_raw_source"]["captured_at"],
            "basis": record["instrument"]["captured_at_basis"],
            "status": verified["temporal_metadata_status"],
        }
        if not isinstance(calibration, dict) or set(calibration) != {
            "check_id", "status", "diagnostic", "source_sha256",
        }:
            raise ValidationError("guide instrument calibration declaration is incomplete")
        for field in ("check_id", "diagnostic"):
            _canonical(calibration[field], f"calibration {field}")
        if calibration["source_sha256"] != raw_sha256:
            raise ValidationError("guide instrument calibration refers to different source bytes")
        if calibration["status"] not in {"failed", "inconclusive", "passed_fixture"}:
            raise ValidationError("guide instrument calibration status is unsupported")
        calibration_view = {
            "check_id": calibration["check_id"],
            "status": calibration["status"],
            "diagnostic": calibration["diagnostic"],
            "source_sha256": raw_sha256,
            "verified": False,
        }
        source_receipt_replay = False
    issues = []
    if rights["review_state"] != "claimed_permitted":
        issues.append("source rights or consent are not independently cleared")
    if calibration_view["status"] == "failed":
        issues.append("instrument calibration failed")
    elif calibration_view["status"] == "inconclusive":
        issues.append("instrument calibration is inconclusive")
    return {
        "acquisition_preview_version": 1,
        "status": "blocked" if issues else "review_only_source_handoff",
        "source_kind": source_kind,
        "raw_source_sha256": raw_sha256,
        "receipt_sha256": expected_receipt_sha256,
        "implementation_replayed": source_receipt_replay,
        "rights_declaration": rights,
        "rights_verified": False,
        "consent_verified": False,
        "timing": timing,
        "calibration": calibration_view,
        "blocking_issues": issues,
        "custody_cleared": False,
        "dataset_registered": False,
        "acquisition_authorized": False,
        "scientific_evidence_eligible": False,
        "canonical_write_performed": False,
    }
