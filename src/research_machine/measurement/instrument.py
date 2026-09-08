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
_STREAM_FIELDS = {
    "stream_id",
    "source_device",
    "channel",
    "sample_rate_hz",
    "clock_source",
    "start_time",
    "clock_drift",
    "missing_intervals",
    "calibration_record",
    "quality_flags",
}
_CLOCK_DRIFT_FIELDS = {"estimate", "unit", "basis"}
_MISSING_INTERVAL_FIELDS = {"start_time", "end_time", "reason"}


def _text(value: Any, field: str, *, optional: bool = False) -> str:
    if optional and value in (None, ""):
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"instrument inspection {field} must be non-empty text")
    if value != value.strip():
        raise ValidationError(
            f"instrument inspection {field} must be canonical without surrounding whitespace"
        )
    return value


def _parse_time(value: Any, field: str) -> tuple[str, datetime]:
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"instrument inspection {field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"instrument inspection {field} must include a UTC offset")
    return text, parsed


def _positive_number(value: Any, field: str) -> float | int:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValidationError(f"instrument inspection {field} must be a finite positive number")
    return value


def _finite_number(value: Any, field: str) -> float | int:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ValidationError(f"instrument inspection {field} must be a finite number")
    return value


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(f"instrument inspection {field} must be an array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError(f"instrument inspection {field} must contain only non-empty strings")
    if any(item != item.strip() for item in value):
        raise ValidationError(
            f"instrument inspection {field} must be canonical without surrounding whitespace"
        )
    if len(set(value)) != len(value):
        raise ValidationError(f"instrument inspection {field} must be unique")
    return list(value)


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise ValidationError(f"instrument inspection {label} missing fields: " + ", ".join(missing))
    if unknown:
        raise ValidationError(f"instrument inspection {label} has unknown fields: " + ", ".join(unknown))


def _stream_metadata(
    value: Any, *, raw_file_sha256: str, conversion_code_sha256: str
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError("instrument inspection streams must be an array")
    streams: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, stream in enumerate(value):
        label = f"streams[{index}]"
        if not isinstance(stream, dict):
            raise ValidationError(f"instrument inspection {label} must be an object")
        _exact_fields(stream, _STREAM_FIELDS, label)
        stream_id = _text(stream["stream_id"], f"{label}.stream_id")
        if stream_id in seen:
            raise ValidationError(f"duplicate instrument inspection stream_id: {stream_id}")
        seen.add(stream_id)
        start_time, _ = _parse_time(stream["start_time"], f"{label}.start_time")
        drift = stream["clock_drift"]
        if not isinstance(drift, dict):
            raise ValidationError(f"instrument inspection {label}.clock_drift must be an object")
        _exact_fields(drift, _CLOCK_DRIFT_FIELDS, f"{label}.clock_drift")
        missing_intervals = stream["missing_intervals"]
        if not isinstance(missing_intervals, list):
            raise ValidationError(f"instrument inspection {label}.missing_intervals must be an array")
        normalized_intervals: list[dict[str, str]] = []
        for interval_index, interval in enumerate(missing_intervals):
            interval_label = f"{label}.missing_intervals[{interval_index}]"
            if not isinstance(interval, dict):
                raise ValidationError(f"instrument inspection {interval_label} must be an object")
            _exact_fields(interval, _MISSING_INTERVAL_FIELDS, interval_label)
            interval_start, parsed_start = _parse_time(
                interval["start_time"], f"{interval_label}.start_time"
            )
            interval_end, parsed_end = _parse_time(
                interval["end_time"], f"{interval_label}.end_time"
            )
            if parsed_end <= parsed_start:
                raise ValidationError(
                    f"instrument inspection {interval_label}.end_time must be after start_time"
                )
            normalized_intervals.append({
                "start_time": interval_start,
                "end_time": interval_end,
                "reason": _text(interval["reason"], f"{interval_label}.reason"),
            })
        streams.append({
            "stream_id": stream_id,
            "source_device": _text(stream["source_device"], f"{label}.source_device"),
            "channel": _text(stream["channel"], f"{label}.channel"),
            "sample_rate_hz": _positive_number(stream["sample_rate_hz"], f"{label}.sample_rate_hz"),
            "clock_source": _text(stream["clock_source"], f"{label}.clock_source"),
            "start_time": start_time,
            "clock_drift": {
                "estimate": _finite_number(drift["estimate"], f"{label}.clock_drift.estimate"),
                "unit": _text(drift["unit"], f"{label}.clock_drift.unit"),
                "basis": _text(drift["basis"], f"{label}.clock_drift.basis"),
            },
            "missing_intervals": normalized_intervals,
            "calibration_record": _text(stream["calibration_record"], f"{label}.calibration_record"),
            "quality_flags": _string_list(stream["quality_flags"], f"{label}.quality_flags"),
            "raw_file_sha256": raw_file_sha256,
            "conversion_code_sha256": conversion_code_sha256,
        })
    return streams


def _json_safe(value: Any, *, canonical_text: bool = False) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError("instrument adapter output must contain only finite numbers")
    if canonical_text and isinstance(value, str) and value != value.strip():
        raise ValidationError(
            "instrument inspection native_metadata text must be canonical without surrounding whitespace"
        )
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    if isinstance(value, list):
        for item in value:
            _json_safe(item, canonical_text=canonical_text)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        if canonical_text and any(not key.strip() or key != key.strip() for key in value):
            raise ValidationError(
                "instrument inspection native_metadata keys must be canonical non-empty text"
            )
        for item in value.values():
            _json_safe(item, canonical_text=canonical_text)
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
        "native_metadata", "warnings", "streams",
    }
    unknown = sorted(set(proposed) - allowed)
    if unknown:
        raise ValidationError("unknown instrument adapter output fields: " + ", ".join(unknown))
    captured_at, _ = _parse_time(proposed.get("captured_at"), "captured_at")
    basis = proposed.get("captured_at_basis")
    if basis not in _TIME_BASES:
        raise ValidationError("instrument inspection captured_at_basis is unsupported")
    metadata = proposed.get("native_metadata", {})
    warnings = proposed.get("warnings", [])
    if not isinstance(metadata, dict):
        raise ValidationError("instrument inspection native_metadata must be an object")
    if not isinstance(warnings, list) or any(
        not isinstance(item, str) or not item.strip() or item != item.strip()
        for item in warnings
    ):
        raise ValidationError(
            "instrument inspection warnings must be canonical non-empty text entries"
        )
    _json_safe(metadata, canonical_text=True)
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    implementation_sha256 = hashlib.sha256(implementation_bytes).hexdigest()
    streams = _stream_metadata(
        proposed.get("streams"),
        raw_file_sha256=source_sha256,
        conversion_code_sha256=implementation_sha256,
    )
    record = {
        "instrument_inspection_version": 1,
        "adapter": {
            "addon_id": manifest.addon_id,
            "addon_version": manifest.version,
            "adapter_id": adapter.adapter_id,
            "authority": "acquisition_metadata_proposal_only",
            "implementation": {
                "locator": implementation.name,
                "sha256": implementation_sha256,
                "size_bytes": len(implementation_bytes),
            },
        },
        "source": {
            "locator": source.name,
            "sha256": source_sha256,
            "size_bytes": len(source_bytes),
            "media_type": media_type,
        },
        "config": committed_config,
        "proposed_raw_source": {
            "locator": source.name,
            "sha256": source_sha256,
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
        "streams": streams,
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
