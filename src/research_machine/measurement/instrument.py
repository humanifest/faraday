"""Low-authority, provider-free instrument source inspection."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from research_machine.addons.models import AddonManifest, InstrumentAdapter
from research_machine.domain.errors import ValidationError


_TIME_BASES = {"device_metadata", "sidecar", "user_supplied", "filesystem_metadata"}


def _text(value: Any, field: str, *, optional: bool = False) -> str:
    if optional and value in (None, ""):
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"instrument inspection {field} must be non-empty text")
    return value


def _json_safe(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError("instrument adapter output must contain only finite numbers")
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    if isinstance(value, list):
        for item in value:
            _json_safe(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json_safe(item)
        return
    raise ValidationError("instrument adapter output must be JSON-compatible")


def inspect_instrument_source(
    manifest: AddonManifest,
    adapter: InstrumentAdapter,
    source_file: Path,
    media_type: str,
    config: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    """Snapshot source bytes and publish only bounded acquisition metadata."""
    source = source_file.expanduser().resolve()
    if not source.is_file():
        raise ValidationError(f"instrument source is not a file: {source}")
    media_type = _text(media_type, "media_type")
    if media_type not in adapter.supported_media_types:
        raise ValidationError(
            f"instrument adapter {adapter.adapter_id} does not support media type {media_type}"
        )
    if not isinstance(config, dict):
        raise ValidationError("instrument adapter config must be an object")
    missing = sorted(set(adapter.required_config_fields) - set(config))
    if missing:
        raise ValidationError(
            "instrument adapter config is missing fields: " + ", ".join(missing)
        )
    unknown_config = sorted(
        set(config)
        - set(adapter.required_config_fields)
        - set(adapter.optional_config_fields)
    )
    if unknown_config:
        raise ValidationError(
            "instrument adapter config has unknown fields: " + ", ".join(unknown_config)
        )
    source_bytes = source.read_bytes()
    implementation_name = inspect.getsourcefile(adapter.inspector)
    if not implementation_name:
        raise ValidationError("instrument adapter implementation source is unavailable")
    implementation = Path(implementation_name).expanduser().resolve()
    if not implementation.is_file():
        raise ValidationError("instrument adapter implementation source is not a file")
    implementation_bytes = implementation.read_bytes()
    committed_config = copy.deepcopy(config)
    try:
        proposed = adapter.inspector(source_bytes, config)
    except Exception as exc:
        raise ValidationError(f"instrument adapter failed: {exc}") from exc
    if not source.is_file() or source.read_bytes() != source_bytes:
        raise ValidationError("instrument adapter modified its source file during inspection")
    if (
        not implementation.is_file()
        or implementation.read_bytes() != implementation_bytes
    ):
        raise ValidationError(
            "instrument adapter modified its implementation file during inspection"
        )
    if config != committed_config:
        raise ValidationError("instrument adapter modified its committed config")
    if not isinstance(proposed, dict):
        raise ValidationError("instrument adapter output must be an object")
    allowed = {
        "captured_at", "captured_at_basis", "acquisition_method",
        "instrument_identifier", "instrument_model", "firmware_version",
        "native_metadata", "warnings",
    }
    unknown = sorted(set(proposed) - allowed)
    if unknown:
        raise ValidationError("unknown instrument adapter output fields: " + ", ".join(unknown))
    captured_at = _text(proposed.get("captured_at"), "captured_at")
    try:
        parsed_time = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("instrument inspection captured_at must be ISO-8601") from exc
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise ValidationError("instrument inspection captured_at must include a UTC offset")
    basis = proposed.get("captured_at_basis")
    if basis not in _TIME_BASES:
        raise ValidationError("instrument inspection captured_at_basis is unsupported")
    metadata = proposed.get("native_metadata", {})
    warnings = proposed.get("warnings", [])
    if not isinstance(metadata, dict):
        raise ValidationError("instrument inspection native_metadata must be an object")
    if not isinstance(warnings, list) or any(
        not isinstance(item, str) or not item.strip() for item in warnings
    ):
        raise ValidationError("instrument inspection warnings must be non-empty text entries")
    _json_safe(metadata)
    record = {
        "instrument_inspection_version": 1,
        "adapter": {
            "addon_id": manifest.addon_id,
            "addon_version": manifest.version,
            "adapter_id": adapter.adapter_id,
            "authority": "acquisition_metadata_proposal_only",
            "implementation": {
                "locator": implementation.name,
                "sha256": hashlib.sha256(implementation_bytes).hexdigest(),
                "size_bytes": len(implementation_bytes),
            },
        },
        "source": {
            "locator": source.name,
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "size_bytes": len(source_bytes),
            "media_type": media_type,
        },
        "config": committed_config,
        "proposed_raw_source": {
            "locator": source.name,
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "captured_at": captured_at,
            "acquisition_method": _text(proposed.get("acquisition_method"), "acquisition_method"),
        },
        "instrument": {
            "identifier": _text(proposed.get("instrument_identifier"), "instrument_identifier"),
            "model": _text(proposed.get("instrument_model"), "instrument_model"),
            "firmware_version": _text(proposed.get("firmware_version"), "firmware_version", optional=True),
            "captured_at_basis": basis,
            "native_metadata": metadata,
        },
        "warnings": warnings,
        "status": "inspection_recorded",
        "scientific_evidence_eligible": False,
        "authorized_actions": [],
        "conclusion_ceiling": (
            "Adapter-proposed acquisition metadata bound to core-hashed source bytes. "
            "No calibration, quality gate, custody chain, dataset, or evidence is approved."
        ),
    }
    _json_safe(record)
    encoded = (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError(f"instrument inspection output path already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{root.name}-", dir=root.parent) as temporary:
        staging = Path(temporary) / root.name
        staging.mkdir()
        (staging / "instrument-inspection.json").write_bytes(encoded)
        try:
            os.replace(staging, root)
        except OSError as exc:
            raise ValidationError(f"could not publish instrument inspection atomically: {exc}") from exc
    return {
        "path": str(root),
        "adapter_id": adapter.adapter_id,
        "source_sha256": record["source"]["sha256"],
        "inspection_sha256": hashlib.sha256(encoded).hexdigest(),
        "status": "inspection_recorded",
        "scientific_evidence_eligible": False,
    }


def verify_instrument_inspection(
    manifest: AddonManifest,
    adapter: InstrumentAdapter,
    source_file: Path,
    media_type: str,
    config: dict[str, Any],
    record_file: Path,
    expected_record_sha256: str,
) -> dict[str, Any]:
    """Re-execute an inspector and require exact canonical record reproduction."""
    expected = expected_record_sha256
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or set(expected) - set("0123456789abcdef")
    ):
        raise ValidationError("instrument inspection expected_record_sha256 must be a lowercase SHA-256")
    record_path = record_file.expanduser().resolve()
    if not record_path.is_file():
        raise ValidationError(f"instrument inspection record is not a file: {record_path}")
    retained = record_path.read_bytes()
    retained_sha256 = hashlib.sha256(retained).hexdigest()
    if retained_sha256 != expected:
        raise ValidationError("instrument inspection record does not match expected_record_sha256")
    with tempfile.TemporaryDirectory(prefix=".instrument-inspection-verify-") as temporary:
        generated_root = Path(temporary) / "recomputed"
        recomputed = inspect_instrument_source(
            manifest, adapter, source_file, media_type, config, generated_root
        )
        generated = (generated_root / "instrument-inspection.json").read_bytes()
    if generated != retained:
        raise ValidationError(
            "instrument inspection record does not exactly recompute from current source, config, and adapter bytes"
        )
    return {
        "status": "instrument_inspection_verified",
        "inspection_sha256": retained_sha256,
        "source_sha256": recomputed["source_sha256"],
        "adapter_id": adapter.adapter_id,
        "addon_id": manifest.addon_id,
        "scientific_evidence_eligible": False,
        "conclusion_ceiling": (
            "Exact local reproduction of an acquisition-metadata proposal only; "
            "no calibration, gate, custody, dataset, or evidence is approved."
        ),
    }
