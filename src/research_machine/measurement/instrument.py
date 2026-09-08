"""Low-authority, provider-free instrument source inspection."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from research_machine.addons.models import AddonManifest, InstrumentAdapter
from research_machine.domain.errors import ValidationError


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
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
_INSTRUMENT_INSPECTION_RECORD_FIELDS = {
    "instrument_inspection_version",
    "adapter",
    "source",
    "config",
    "proposed_raw_source",
    "instrument",
    "temporal_metadata",
    "streams",
    "warnings",
    "status",
    "scientific_evidence_eligible",
    "authorized_actions",
    "conclusion_ceiling",
}
_INSTRUMENT_ADAPTER_FIELDS = {
    "addon_id",
    "addon_version",
    "adapter_id",
    "authority",
    "implementation",
}
_INSTRUMENT_IMPLEMENTATION_FIELDS = {"locator", "sha256", "size_bytes"}
_INSTRUMENT_SOURCE_FIELDS = {"locator", "sha256", "size_bytes", "media_type"}
_INSTRUMENT_PROPOSED_RAW_SOURCE_FIELDS = {
    "locator",
    "sha256",
    "captured_at",
    "acquisition_method",
}
_INSTRUMENT_FIELDS = {
    "identifier",
    "model",
    "firmware_version",
    "captured_at_basis",
    "native_metadata",
}
_INSTRUMENT_TEMPORAL_METADATA_FIELDS = {"status", "stream_count", "limitations"}
_INSTRUMENT_STREAM_RECORD_FIELDS = _STREAM_FIELDS | {
    "raw_file_sha256",
    "conversion_code_sha256",
}
_CLOCK_DRIFT_FIELDS = {"estimate", "uncertainty", "unit", "basis"}
_CLOCK_DRIFT_UNITS = {"s", "ms", "us", "ns", "ppm"}
_MISSING_INTERVAL_FIELDS = {"start_time", "end_time", "reason"}
_TIMING_ASSESSMENT_SPEC_FIELDS = {
    "assessment_id",
    "lag_window",
    "maximum_uncertainty_fraction",
    "required_streams",
    "events",
}
_TIMING_LAG_WINDOW_FIELDS = {"duration", "unit", "basis"}
_TIMING_REQUIRED_STREAM_FIELDS = {"stream_id", "channel", "purpose"}
_TIMING_EVENT_FIELDS = {"event_id", "stream_id", "event_time"}
_STREAM_TIMING_RECORD_FIELDS = {
    "stream_timing_assessment_version",
    "assessment_id",
    "inspection",
    "specification",
    "required_streams",
    "events",
    "findings",
    "status",
    "scientific_evidence_eligible",
    "authorized_actions",
    "conclusion_ceiling",
}
_STREAM_TIMING_INSPECTION_FIELDS = {
    "sha256",
    "size_bytes",
    "stream_count",
    "temporal_metadata_status",
}
_STREAM_TIMING_SPECIFICATION_FIELDS = {
    "sha256",
    "size_bytes",
    "lag_window",
    "maximum_uncertainty_fraction",
}
_TEMPORAL_ORDER_SPEC_FIELDS = {"assessment_id", "order_checks"}
_TEMPORAL_ORDER_CHECK_FIELDS = {
    "check_id",
    "first_event_id",
    "second_event_id",
    "expected_relation",
    "minimum_separation",
    "maximum_separation",
    "scientific_question",
}
_TEMPORAL_ORDER_RECORD_FIELDS = {
    "temporal_order_assessment_version",
    "assessment_id",
    "timing_assessment",
    "specification",
    "order_checks",
    "findings",
    "status",
    "scientific_evidence_eligible",
    "authorized_actions",
    "conclusion_ceiling",
}
_TEMPORAL_ORDER_SOURCE_FIELDS = {"sha256", "size_bytes"}
_TEMPORAL_ORDER_TIMING_FIELDS = {"sha256", "size_bytes", "status"}
_TIME_BOUND_FIELDS = {"duration", "unit"}
_EXPECTED_TEMPORAL_RELATIONS = {
    "first_precedes_second",
    "second_precedes_first",
    "indeterminate_within_uncertainty",
}
_ABSOLUTE_TIME_UNITS_TO_SECONDS = {
    "s": 1.0,
    "ms": 0.001,
    "us": 0.000001,
    "ns": 0.000000001,
}
_MAX_ADAPTER_OUTPUT_BYTES = 1_000_000
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 50_000
_MAX_JSON_STRING_BYTES = 262_144


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


def _nonnegative_number(value: Any, field: str) -> float | int:
    number = _finite_number(value, field)
    if number < 0:
        raise ValidationError(f"instrument inspection {field} must be non-negative")
    return number


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


def _canonical_text_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(f"instrument inspection {field} must be an array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError(f"instrument inspection {field} must contain only non-empty strings")
    if any(item != item.strip() for item in value):
        raise ValidationError(
            f"instrument inspection {field} must be canonical without surrounding whitespace"
        )
    return list(value)


def _stable_identifier(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _IDENTIFIER.fullmatch(text):
        raise ValidationError(
            f"instrument inspection {field} must be a stable lowercase identifier"
        )
    return text


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise ValidationError(f"instrument inspection {label} missing fields: " + ", ".join(missing))
    if unknown:
        raise ValidationError(f"instrument inspection {label} has unknown fields: " + ", ".join(unknown))


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _load_json_object_and_sha256(path: Path, label: str) -> tuple[dict[str, Any], bytes, str]:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise ValidationError(f"{label} is not a file: {source}")
    try:
        content = source.read_bytes()
        value = json.loads(
            content,
            parse_constant=_reject_nonfinite_json,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(f"{label} is not strict valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value, content, hashlib.sha256(content).hexdigest()


def _canonical_payload_sha256(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValidationError("instrument inspection value is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or set(text) - set("0123456789abcdef"):
        raise ValidationError(f"instrument inspection {field} must be a lowercase SHA-256")
    return text


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
        stream_id = _stable_identifier(stream["stream_id"], f"{label}.stream_id")
        if stream_id in seen:
            raise ValidationError(f"duplicate instrument inspection stream_id: {stream_id}")
        seen.add(stream_id)
        start_time, parsed_stream_start = _parse_time(
            stream["start_time"], f"{label}.start_time"
        )
        drift = stream["clock_drift"]
        if not isinstance(drift, dict):
            raise ValidationError(f"instrument inspection {label}.clock_drift must be an object")
        _exact_fields(drift, _CLOCK_DRIFT_FIELDS, f"{label}.clock_drift")
        missing_intervals = stream["missing_intervals"]
        if not isinstance(missing_intervals, list):
            raise ValidationError(f"instrument inspection {label}.missing_intervals must be an array")
        normalized_intervals: list[dict[str, str]] = []
        previous_end: datetime | None = None
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
            if parsed_start < parsed_stream_start:
                raise ValidationError(
                    f"instrument inspection {interval_label}.start_time must not precede stream start_time"
                )
            if previous_end is not None and parsed_start < previous_end:
                raise ValidationError(
                    f"instrument inspection {interval_label} must be ordered and non-overlapping"
                )
            previous_end = parsed_end
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
                "uncertainty": _nonnegative_number(
                    drift["uncertainty"], f"{label}.clock_drift.uncertainty"
                ),
                "unit": _text(drift["unit"], f"{label}.clock_drift.unit"),
                "basis": _text(drift["basis"], f"{label}.clock_drift.basis"),
            },
            "missing_intervals": normalized_intervals,
            "calibration_record": _text(stream["calibration_record"], f"{label}.calibration_record"),
            "quality_flags": _string_list(stream["quality_flags"], f"{label}.quality_flags"),
            "raw_file_sha256": raw_file_sha256,
            "conversion_code_sha256": conversion_code_sha256,
        })
        if streams[-1]["clock_drift"]["unit"] not in _CLOCK_DRIFT_UNITS:
            raise ValidationError(
                f"instrument inspection {label}.clock_drift.unit is unsupported"
            )
    return streams


def _temporal_metadata_summary(streams: list[dict[str, Any]]) -> dict[str, Any]:
    if not streams:
        return {
            "status": "not_provided",
            "stream_count": 0,
            "limitations": [
                "No typed stream metadata was proposed; synchronized timing cannot be assessed from this inspection."
            ],
        }
    limitations = [
        "Stream metadata is an adapter proposal bound to raw bytes and adapter code; it is not calibration, synchronization validation, or custody approval.",
        "Clock-drift estimates and uncertainties remain asserted metadata until a separate quality gate verifies timing against the frozen protocol.",
    ]
    if any(stream["missing_intervals"] for stream in streams):
        limitations.append(
            "Missing intervals are preserved as acquisition limitations and must be handled by later custody or analysis gates."
        )
    return {
        "status": "proposed_unverified",
        "stream_count": len(streams),
        "limitations": limitations,
    }


def _json_safe(
    value: Any,
    *,
    canonical_text: bool = False,
    _depth: int = 0,
    _seen: set[int] | None = None,
    _node_count: list[int] | None = None,
) -> None:
    if _seen is None:
        _seen = set()
    if _node_count is None:
        _node_count = [0]
    if _depth > _MAX_JSON_DEPTH:
        raise ValidationError("instrument adapter output exceeds bounded JSON depth")
    _node_count[0] += 1
    if _node_count[0] > _MAX_JSON_NODES:
        raise ValidationError("instrument adapter output exceeds bounded JSON node count")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError("instrument adapter output must contain only finite numbers")
    if isinstance(value, str) and len(value.encode("utf-8")) > _MAX_JSON_STRING_BYTES:
        raise ValidationError("instrument adapter output exceeds bounded JSON string size")
    if canonical_text and isinstance(value, str) and value != value.strip():
        raise ValidationError(
            "instrument inspection native_metadata text must be canonical without surrounding whitespace"
        )
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    if isinstance(value, list):
        marker = id(value)
        if marker in _seen:
            raise ValidationError("instrument adapter output must not contain cycles")
        _seen.add(marker)
        for item in value:
            _json_safe(
                item,
                canonical_text=canonical_text,
                _depth=_depth + 1,
                _seen=_seen,
                _node_count=_node_count,
            )
        _seen.remove(marker)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        marker = id(value)
        if marker in _seen:
            raise ValidationError("instrument adapter output must not contain cycles")
        _seen.add(marker)
        if canonical_text and any(not key.strip() or key != key.strip() for key in value):
            raise ValidationError(
                "instrument inspection native_metadata keys must be canonical non-empty text"
            )
        for key in value:
            if len(key.encode("utf-8")) > _MAX_JSON_STRING_BYTES:
                raise ValidationError("instrument adapter output exceeds bounded JSON string size")
        for item in value.values():
            _json_safe(
                item,
                canonical_text=canonical_text,
                _depth=_depth + 1,
                _seen=_seen,
                _node_count=_node_count,
            )
        _seen.remove(marker)
        return
    raise ValidationError("instrument adapter output must be JSON-compatible")


def _bounded_json_bytes(value: Any, label: str, *, max_bytes: int) -> bytes:
    _json_safe(value)
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be JSON-compatible") from exc
    if len(encoded) > max_bytes:
        raise ValidationError(
            f"{label} exceeds bounded JSON size of {max_bytes} bytes"
        )
    return encoded


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
    _bounded_json_bytes(
        proposed,
        "instrument adapter output",
        max_bytes=_MAX_ADAPTER_OUTPUT_BYTES,
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
        "temporal_metadata": _temporal_metadata_summary(streams),
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


def _time_unit_seconds(unit: Any, field: str) -> float:
    text = _text(unit, field)
    if text not in _ABSOLUTE_TIME_UNITS_TO_SECONDS:
        raise ValidationError(f"instrument inspection {field} must use s, ms, us, or ns")
    return _ABSOLUTE_TIME_UNITS_TO_SECONDS[text]


def _time_bound_seconds(value: Any, field: str, *, allow_zero: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"instrument inspection {field} must be an object")
    _exact_fields(value, _TIME_BOUND_FIELDS, field)
    if allow_zero:
        duration = _nonnegative_number(value["duration"], f"{field}.duration")
    else:
        duration = _positive_number(value["duration"], f"{field}.duration")
    unit = _text(value["unit"], f"{field}.unit")
    return {
        "duration": duration,
        "unit": unit,
        "seconds": duration * _time_unit_seconds(unit, f"{field}.unit"),
    }


def _ordered_timing_streams(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValidationError("instrument inspection timing required_streams must be a non-empty array")
    streams: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, stream in enumerate(value):
        label = f"timing.required_streams[{index}]"
        if not isinstance(stream, dict):
            raise ValidationError(f"instrument inspection {label} must be an object")
        _exact_fields(stream, _TIMING_REQUIRED_STREAM_FIELDS, label)
        stream_id = _stable_identifier(stream["stream_id"], f"{label}.stream_id")
        if stream_id in seen:
            raise ValidationError("instrument inspection timing required_streams must be unique")
        seen.add(stream_id)
        streams.append({
            "stream_id": stream_id,
            "channel": _text(stream["channel"], f"{label}.channel"),
            "purpose": _text(stream["purpose"], f"{label}.purpose"),
        })
    return streams


def _ordered_timing_events(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValidationError("instrument inspection timing events must be a non-empty array")
    events: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, event in enumerate(value):
        label = f"timing.events[{index}]"
        if not isinstance(event, dict):
            raise ValidationError(f"instrument inspection {label} must be an object")
        _exact_fields(event, _TIMING_EVENT_FIELDS, label)
        event_id = _stable_identifier(event["event_id"], f"{label}.event_id")
        if event_id in seen:
            raise ValidationError("instrument inspection timing events must be unique")
        seen.add(event_id)
        event_time, _ = _parse_time(event["event_time"], f"{label}.event_time")
        events.append({
            "event_id": event_id,
            "stream_id": _stable_identifier(event["stream_id"], f"{label}.stream_id"),
            "event_time": event_time,
        })
    return events


def _normalize_timing_spec(spec: dict[str, Any]) -> dict[str, Any]:
    _exact_fields(spec, _TIMING_ASSESSMENT_SPEC_FIELDS, "timing")
    lag_window = spec["lag_window"]
    if not isinstance(lag_window, dict):
        raise ValidationError("instrument inspection timing.lag_window must be an object")
    _exact_fields(lag_window, _TIMING_LAG_WINDOW_FIELDS, "timing.lag_window")
    duration = _positive_number(lag_window["duration"], "timing.lag_window.duration")
    unit = _text(lag_window["unit"], "timing.lag_window.unit")
    unit_seconds = _time_unit_seconds(unit, "timing.lag_window.unit")
    maximum_fraction = _positive_number(
        spec["maximum_uncertainty_fraction"],
        "timing.maximum_uncertainty_fraction",
    )
    if maximum_fraction > 1:
        raise ValidationError(
            "instrument inspection timing.maximum_uncertainty_fraction must be at most 1"
        )
    return {
        "assessment_id": _stable_identifier(spec["assessment_id"], "timing.assessment_id"),
        "lag_window": {
            "duration": duration,
            "unit": unit,
            "seconds": duration * unit_seconds,
            "basis": _text(lag_window["basis"], "timing.lag_window.basis"),
        },
        "maximum_uncertainty_fraction": maximum_fraction,
        "required_streams": _ordered_timing_streams(spec["required_streams"]),
        "events": _ordered_timing_events(spec["events"]),
    }


def _clock_uncertainty_seconds(stream: dict[str, Any]) -> float | None:
    drift = stream["clock_drift"]
    unit = drift["unit"]
    if unit not in _ABSOLUTE_TIME_UNITS_TO_SECONDS:
        return None
    return float(drift["uncertainty"]) * _ABSOLUTE_TIME_UNITS_TO_SECONDS[unit]


def _normalize_temporal_order_spec(spec: dict[str, Any]) -> dict[str, Any]:
    _exact_fields(spec, _TEMPORAL_ORDER_SPEC_FIELDS, "temporal_order")
    checks = spec["order_checks"]
    if not isinstance(checks, list) or not checks:
        raise ValidationError("instrument inspection temporal_order.order_checks must be a non-empty array")
    normalized_checks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, check in enumerate(checks):
        label = f"temporal_order.order_checks[{index}]"
        if not isinstance(check, dict):
            raise ValidationError(f"instrument inspection {label} must be an object")
        _exact_fields(check, _TEMPORAL_ORDER_CHECK_FIELDS, label)
        check_id = _stable_identifier(check["check_id"], f"{label}.check_id")
        if check_id in seen:
            raise ValidationError("instrument inspection temporal_order check_id must be unique")
        seen.add(check_id)
        first_event_id = _stable_identifier(check["first_event_id"], f"{label}.first_event_id")
        second_event_id = _stable_identifier(check["second_event_id"], f"{label}.second_event_id")
        if first_event_id == second_event_id:
            raise ValidationError("instrument inspection temporal_order events must be distinct")
        expected_relation = _text(check["expected_relation"], f"{label}.expected_relation")
        if expected_relation not in _EXPECTED_TEMPORAL_RELATIONS:
            raise ValidationError("instrument inspection temporal_order expected_relation is unsupported")
        minimum = _time_bound_seconds(
            check["minimum_separation"], f"{label}.minimum_separation", allow_zero=True
        )
        maximum = _time_bound_seconds(check["maximum_separation"], f"{label}.maximum_separation")
        if maximum["seconds"] < minimum["seconds"]:
            raise ValidationError(
                "instrument inspection temporal_order maximum_separation must be at least minimum_separation"
            )
        normalized_checks.append({
            "check_id": check_id,
            "first_event_id": first_event_id,
            "second_event_id": second_event_id,
            "expected_relation": expected_relation,
            "minimum_separation": minimum,
            "maximum_separation": maximum,
            "scientific_question": _text(check["scientific_question"], f"{label}.scientific_question"),
        })
    return {
        "assessment_id": _stable_identifier(spec["assessment_id"], "temporal_order.assessment_id"),
        "order_checks": normalized_checks,
    }


def _timing_events_by_id(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    events = record.get("events")
    if not isinstance(events, list):
        raise ValidationError("stream timing assessment events must be an array")
    events_by_id: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValidationError(f"stream timing assessment events[{index}] must be an object")
        event_id = _stable_identifier(event.get("event_id"), f"timing.events[{index}].event_id")
        if event_id in events_by_id:
            raise ValidationError(f"stream timing assessment has duplicate event_id: {event_id}")
        events_by_id[event_id] = event
    return events_by_id


def _classify_event_order(
    first_event: dict[str, Any],
    second_event: dict[str, Any],
    minimum_seconds: float,
) -> tuple[str, float, float]:
    _, first_time = _parse_time(first_event.get("event_time"), "temporal_order.first_event_time")
    _, second_time = _parse_time(second_event.get("event_time"), "temporal_order.second_event_time")
    first_uncertainty = _nonnegative_number(
        first_event.get("clock_uncertainty_seconds"),
        "temporal_order.first_event.clock_uncertainty_seconds",
    )
    second_uncertainty = _nonnegative_number(
        second_event.get("clock_uncertainty_seconds"),
        "temporal_order.second_event.clock_uncertainty_seconds",
    )
    point_delta_seconds = (second_time - first_time).total_seconds()
    conservative_gap_seconds = abs(point_delta_seconds) - float(first_uncertainty) - float(second_uncertainty)
    if point_delta_seconds > 0 and conservative_gap_seconds >= minimum_seconds:
        return "first_precedes_second", point_delta_seconds, conservative_gap_seconds
    if point_delta_seconds < 0 and conservative_gap_seconds >= minimum_seconds:
        return "second_precedes_first", point_delta_seconds, conservative_gap_seconds
    return "indeterminate_within_uncertainty", point_delta_seconds, conservative_gap_seconds


def _finding(
    code: str,
    message: str,
    *,
    severity: str = "error",
    stream_id: str | None = None,
    event_id: str | None = None,
) -> dict[str, str]:
    finding = {"severity": severity, "code": code, "message": message}
    if stream_id:
        finding["stream_id"] = stream_id
    if event_id:
        finding["event_id"] = event_id
    return finding


def assess_temporal_order(
    timing_assessment_file: Path,
    expected_timing_assessment_sha256: str,
    spec_file: Path,
    output: Path,
) -> dict[str, Any]:
    """Publish a non-evidentiary event-order assessment from trusted timing bytes."""
    expected = _sha256(
        expected_timing_assessment_sha256, "expected_timing_assessment_sha256"
    )
    timing, timing_bytes, retained_sha256 = _load_json_object_and_sha256(
        timing_assessment_file, "stream timing assessment"
    )
    if retained_sha256 != expected:
        raise ValidationError(
            "stream timing assessment does not match expected_timing_assessment_sha256"
        )
    spec, spec_bytes, spec_sha256 = _load_json_object_and_sha256(
        spec_file, "temporal order assessment specification"
    )
    normalized_spec = _normalize_temporal_order_spec(spec)
    if timing.get("stream_timing_assessment_version") != 1:
        raise ValidationError("unsupported stream timing assessment")
    if timing.get("scientific_evidence_eligible") is not False:
        raise ValidationError("stream timing assessment must remain non-evidentiary")
    events_by_id = _timing_events_by_id(timing)
    findings: list[dict[str, str]] = []
    if timing.get("status") != "timing_feasibility_passed":
        findings.append(_finding(
            "UPSTREAM_TIMING_FEASIBILITY_NOT_PASSED",
            "Temporal order fails closed because the upstream timing-feasibility assessment did not pass.",
        ))

    check_results: list[dict[str, Any]] = []
    for check in normalized_spec["order_checks"]:
        check_id = check["check_id"]
        first_event = events_by_id.get(check["first_event_id"])
        second_event = events_by_id.get(check["second_event_id"])
        result: dict[str, Any] = {
            "check_id": check_id,
            "first_event_id": check["first_event_id"],
            "second_event_id": check["second_event_id"],
            "expected_relation": check["expected_relation"],
            "minimum_separation": check["minimum_separation"],
            "maximum_separation": check["maximum_separation"],
            "scientific_question": check["scientific_question"],
        }
        if first_event is None or second_event is None:
            result["observed_relation"] = "not_assessed"
            result["status"] = "failed"
            findings.append(_finding(
                "ORDER_EVENT_ABSENT",
                "A temporal-order check references an event absent from the timing assessment.",
            ))
            check_results.append(result)
            continue
        if first_event.get("status") != "assessed" or second_event.get("status") != "assessed":
            result["observed_relation"] = "not_assessed"
            result["status"] = "failed"
            findings.append(_finding(
                "ORDER_EVENT_NOT_ASSESSED",
                "A temporal-order check references an event without assessed clock uncertainty.",
            ))
            check_results.append(result)
            continue
        if first_event.get("overlapping_missing_intervals") or second_event.get(
            "overlapping_missing_intervals"
        ):
            result["observed_relation"] = "not_assessed"
            result["status"] = "failed"
            findings.append(_finding(
                "ORDER_EVENT_OVERLAPS_MISSING_INTERVAL",
                "A temporal-order check references an event whose uncertainty overlaps missing or corrupted data.",
            ))
            check_results.append(result)
            continue

        observed, point_delta, conservative_gap = _classify_event_order(
            first_event,
            second_event,
            float(check["minimum_separation"]["seconds"]),
        )
        result["observed_relation"] = observed
        result["point_delta_seconds"] = point_delta
        result["conservative_gap_seconds"] = conservative_gap
        if observed == "indeterminate_within_uncertainty" and observed != check["expected_relation"]:
            result["status"] = "failed"
            findings.append(_finding(
                "ORDER_INDETERMINATE_WITHIN_UNCERTAINTY",
                "The event order is not directionally resolvable within measurement uncertainty.",
            ))
        elif (
            observed in {"first_precedes_second", "second_precedes_first"}
            and abs(point_delta) > float(check["maximum_separation"]["seconds"])
        ):
            result["status"] = "failed"
            findings.append(_finding(
                "ORDER_OUTSIDE_REGISTERED_WINDOW",
                "The event order is directionally clear but outside the registered maximum separation.",
            ))
        elif observed != check["expected_relation"]:
            result["status"] = "failed"
            findings.append(_finding(
                "ORDER_CONTRADICTS_EXPECTATION",
                "The measured event order does not match the registered expected relation.",
            ))
        elif observed == "indeterminate_within_uncertainty":
            result["status"] = "warning"
            findings.append(_finding(
                "ORDER_INDETERMINATE_WITHIN_UNCERTAINTY",
                "The registered expectation was indeterminate, so no directional order is asserted.",
                severity="warning",
            ))
        else:
            result["status"] = "passed"
        check_results.append(result)

    status = "temporal_order_failed" if any(
        finding["severity"] == "error" for finding in findings
    ) else "temporal_order_passed"
    record = {
        "temporal_order_assessment_version": 1,
        "assessment_id": normalized_spec["assessment_id"],
        "timing_assessment": {
            "sha256": retained_sha256,
            "size_bytes": len(timing_bytes),
            "status": timing.get("status"),
        },
        "specification": {
            "sha256": spec_sha256,
            "size_bytes": len(spec_bytes),
        },
        "order_checks": check_results,
        "findings": findings,
        "status": status,
        "scientific_evidence_eligible": False,
        "authorized_actions": [],
        "conclusion_ceiling": (
            "Provider-free temporal-order classification from a trusted timing assessment only. "
            "It may distinguish clear order, reversal, registered-window misses, or timing "
            "indeterminacy within measurement uncertainty, but it does not establish causality, "
            "mechanism, intent, calibration truth, dataset registration, or scientific evidence."
        ),
    }
    _json_safe(record)
    encoded = (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError(f"temporal order assessment output path already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{root.name}-", dir=root.parent) as temporary:
        staging = Path(temporary) / root.name
        staging.mkdir()
        (staging / "temporal-order-assessment.json").write_bytes(encoded)
        try:
            os.replace(staging, root)
        except OSError as exc:
            raise ValidationError(f"could not publish temporal order assessment atomically: {exc}") from exc
    return {
        "path": str(root),
        "assessment_id": normalized_spec["assessment_id"],
        "timing_assessment_sha256": retained_sha256,
        "specification_sha256": spec_sha256,
        "assessment_sha256": hashlib.sha256(encoded).hexdigest(),
        "status": status,
        "finding_count": len(findings),
        "scientific_evidence_eligible": False,
    }


def verify_temporal_order_assessment_record(
    record_file: Path,
    expected_record_sha256: str,
    *,
    expected_timing_assessment_sha256: str | None = None,
    expected_specification_sha256: str | None = None,
) -> dict[str, Any]:
    """Replay a retained temporal-order assessment record from current bytes."""
    expected_record = _sha256(expected_record_sha256, "expected_record_sha256")
    record, content, retained_sha256 = _load_json_object_and_sha256(
        record_file, "temporal order assessment record"
    )
    if retained_sha256 != expected_record:
        raise ValidationError(
            "temporal order assessment record does not match expected_record_sha256"
        )
    _exact_fields(record, _TEMPORAL_ORDER_RECORD_FIELDS, "temporal_order record")
    if record["temporal_order_assessment_version"] != 1:
        raise ValidationError("unsupported temporal order assessment record")
    assessment_id = _stable_identifier(
        record["assessment_id"], "temporal_order record assessment_id"
    )
    timing = record["timing_assessment"]
    if not isinstance(timing, dict):
        raise ValidationError("temporal order assessment timing_assessment must be an object")
    _exact_fields(timing, _TEMPORAL_ORDER_TIMING_FIELDS, "temporal_order timing_assessment")
    timing_sha256 = _sha256(
        timing["sha256"], "temporal_order timing_assessment.sha256"
    )
    if expected_timing_assessment_sha256 is not None and timing_sha256 != _sha256(
        expected_timing_assessment_sha256, "expected_timing_assessment_sha256"
    ):
        raise ValidationError("temporal order assessment timing SHA-256 mismatch")
    if not isinstance(timing["size_bytes"], int) or isinstance(timing["size_bytes"], bool) or timing["size_bytes"] <= 0:
        raise ValidationError("temporal order assessment timing size_bytes must be a positive integer")
    timing_status = _text(timing["status"], "temporal_order timing_assessment.status")
    if timing_status not in {"timing_feasibility_passed", "timing_feasibility_failed"}:
        raise ValidationError("temporal order assessment timing status is unsupported")
    specification = record["specification"]
    if not isinstance(specification, dict):
        raise ValidationError("temporal order assessment specification must be an object")
    _exact_fields(specification, _TEMPORAL_ORDER_SOURCE_FIELDS, "temporal_order specification")
    specification_sha256 = _sha256(
        specification["sha256"], "temporal_order specification.sha256"
    )
    if expected_specification_sha256 is not None and specification_sha256 != _sha256(
        expected_specification_sha256, "expected_specification_sha256"
    ):
        raise ValidationError("temporal order assessment specification SHA-256 mismatch")
    if not isinstance(specification["size_bytes"], int) or isinstance(specification["size_bytes"], bool) or specification["size_bytes"] <= 0:
        raise ValidationError("temporal order assessment specification size_bytes must be a positive integer")
    order_checks = record["order_checks"]
    if not isinstance(order_checks, list) or not order_checks:
        raise ValidationError("temporal order assessment order_checks must be a non-empty array")
    check_statuses: list[str] = []
    seen_checks: set[str] = set()
    for index, check in enumerate(order_checks):
        if not isinstance(check, dict):
            raise ValidationError(f"temporal order assessment order_checks[{index}] must be an object")
        check_id = _stable_identifier(
            check.get("check_id"), f"temporal_order order_checks[{index}].check_id"
        )
        if check_id in seen_checks:
            raise ValidationError("temporal order assessment check_id must be unique")
        seen_checks.add(check_id)
        observed_relation = _text(
            check.get("observed_relation"),
            f"temporal_order order_checks[{index}].observed_relation",
        )
        if observed_relation not in _EXPECTED_TEMPORAL_RELATIONS | {"not_assessed"}:
            raise ValidationError("temporal order assessment observed_relation is unsupported")
        status = _text(check.get("status"), f"temporal_order order_checks[{index}].status")
        if status not in {"passed", "warning", "failed"}:
            raise ValidationError("temporal order assessment check status is unsupported")
        check_statuses.append(status)
    findings = record["findings"]
    if not isinstance(findings, list):
        raise ValidationError("temporal order assessment findings must be an array")
    error_findings = 0
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise ValidationError(f"temporal order assessment findings[{index}] must be an object")
        severity = _text(
            finding.get("severity"), f"temporal_order findings[{index}].severity"
        )
        if severity not in {"warning", "error"}:
            raise ValidationError("temporal order assessment finding severity is unsupported")
        _text(finding.get("code"), f"temporal_order findings[{index}].code")
        _text(finding.get("message"), f"temporal_order findings[{index}].message")
        if severity == "error":
            error_findings += 1
    status = _text(record["status"], "temporal_order record status")
    if status not in {"temporal_order_passed", "temporal_order_failed"}:
        raise ValidationError("temporal order assessment status is unsupported")
    if record["scientific_evidence_eligible"] is not False:
        raise ValidationError("temporal order assessment must remain non-evidentiary")
    if record["authorized_actions"] != []:
        raise ValidationError("temporal order assessment must not authorize actions")
    _text(record["conclusion_ceiling"], "temporal_order conclusion_ceiling")
    if status == "temporal_order_passed" and (
        error_findings or any(value == "failed" for value in check_statuses)
    ):
        raise ValidationError("temporal order passed record contains failed checks")
    if status == "temporal_order_failed" and not (
        error_findings or any(value == "failed" for value in check_statuses)
    ):
        raise ValidationError("temporal order failed record lacks failed checks")
    return {
        "status": "temporal_order_assessment_record_verified",
        "record_sha256": retained_sha256,
        "record_size_bytes": len(content),
        "assessment_id": assessment_id,
        "record_status": status,
        "timing_assessment_sha256": timing_sha256,
        "timing_assessment_status": timing_status,
        "specification_sha256": specification_sha256,
        "check_count": len(order_checks),
        "failed_check_count": sum(value == "failed" for value in check_statuses),
        "warning_check_count": sum(value == "warning" for value in check_statuses),
        "finding_count": len(findings),
        "scientific_evidence_eligible": False,
    }


def assess_stream_timing(
    inspection_file: Path,
    expected_inspection_sha256: str,
    spec_file: Path,
    output: Path,
) -> dict[str, Any]:
    """Publish a non-evidentiary timing-feasibility assessment from trusted bytes."""
    expected = _sha256(expected_inspection_sha256, "expected_inspection_sha256")
    inspection, inspection_bytes, retained_sha256 = _load_json_object_and_sha256(
        inspection_file, "instrument inspection record"
    )
    if retained_sha256 != expected:
        raise ValidationError(
            "instrument inspection record does not match expected_inspection_sha256"
        )
    spec, spec_bytes, spec_sha256 = _load_json_object_and_sha256(
        spec_file, "instrument timing assessment specification"
    )
    normalized_spec = _normalize_timing_spec(spec)
    if inspection.get("instrument_inspection_version") != 1:
        raise ValidationError("unsupported instrument inspection record")
    if inspection.get("status") != "inspection_recorded":
        raise ValidationError("instrument inspection record is not recorded")
    if inspection.get("scientific_evidence_eligible") is not False:
        raise ValidationError("instrument inspection record must remain non-evidentiary")

    streams = inspection.get("streams")
    if not isinstance(streams, list):
        raise ValidationError("instrument inspection record streams must be an array")
    temporal = inspection.get("temporal_metadata")
    if not isinstance(temporal, dict):
        raise ValidationError("instrument inspection record lacks temporal_metadata")

    streams_by_id: dict[str, dict[str, Any]] = {}
    for index, stream in enumerate(streams):
        if not isinstance(stream, dict):
            raise ValidationError(f"instrument inspection record streams[{index}] must be an object")
        stream_id = _stable_identifier(stream.get("stream_id"), f"record.streams[{index}].stream_id")
        if stream_id in streams_by_id:
            raise ValidationError(f"instrument inspection record has duplicate stream_id: {stream_id}")
        streams_by_id[stream_id] = stream

    findings: list[dict[str, str]] = []
    if temporal.get("status") != "proposed_unverified":
        findings.append(_finding(
            "STREAM_METADATA_NOT_PROVIDED",
            "The inspection record does not contain typed stream metadata; timing feasibility fails closed.",
        ))
    if not streams_by_id:
        findings.append(_finding(
            "NO_STREAMS_AVAILABLE",
            "No streams are available to assess required channels or event timing.",
        ))

    required_stream_results: list[dict[str, Any]] = []
    for required in normalized_spec["required_streams"]:
        stream_id = required["stream_id"]
        stream = streams_by_id.get(stream_id)
        if stream is None:
            findings.append(_finding(
                "REQUIRED_STREAM_ABSENT",
                "A required stream from the timing specification is absent from the inspection record.",
                stream_id=stream_id,
            ))
            required_stream_results.append({
                **required,
                "status": "absent",
            })
            continue
        observed_channel = stream.get("channel")
        status = "present"
        if observed_channel != required["channel"]:
            status = "channel_mismatch"
            findings.append(_finding(
                "REQUIRED_CHANNEL_MISMATCH",
                "A required stream is present but its inspected channel differs from the timing specification.",
                stream_id=stream_id,
            ))
        required_stream_results.append({
            **required,
            "observed_channel": observed_channel,
            "status": status,
        })

    lag_seconds = float(normalized_spec["lag_window"]["seconds"])
    max_fraction = float(normalized_spec["maximum_uncertainty_fraction"])
    event_results: list[dict[str, Any]] = []
    for event in normalized_spec["events"]:
        stream_id = event["stream_id"]
        event_id = event["event_id"]
        stream = streams_by_id.get(stream_id)
        event_result: dict[str, Any] = {
            **event,
            "status": "assessed",
        }
        if stream is None:
            event_result["status"] = "stream_absent"
            findings.append(_finding(
                "EVENT_STREAM_ABSENT",
                "An event references a stream absent from the inspection record.",
                stream_id=stream_id,
                event_id=event_id,
            ))
            event_results.append(event_result)
            continue

        uncertainty_seconds = _clock_uncertainty_seconds(stream)
        if uncertainty_seconds is None:
            event_result["status"] = "unsupported_uncertainty_unit"
            findings.append(_finding(
                "CLOCK_UNCERTAINTY_UNIT_NOT_ABSOLUTE",
                "Clock uncertainty is recorded in a relative unit and cannot be compared with the tested lag window.",
                stream_id=stream_id,
                event_id=event_id,
            ))
            event_results.append(event_result)
            continue
        event_result["clock_uncertainty_seconds"] = uncertainty_seconds
        uncertainty_fraction = uncertainty_seconds / lag_seconds
        event_result["uncertainty_fraction_of_lag_window"] = uncertainty_fraction
        if uncertainty_fraction >= max_fraction:
            findings.append(_finding(
                "CLOCK_UNCERTAINTY_APPROACHES_LAG_WINDOW",
                "Clock uncertainty reaches or exceeds the specification's maximum fraction of the tested lag window.",
                stream_id=stream_id,
                event_id=event_id,
            ))

        _, parsed_event = _parse_time(event["event_time"], f"timing.events.{event_id}.event_time")
        _, parsed_stream_start = _parse_time(
            stream.get("start_time"), f"record.streams.{stream_id}.start_time"
        )
        if parsed_event < parsed_stream_start:
            findings.append(_finding(
                "EVENT_PRECEDES_STREAM_START",
                "The event time precedes the inspected stream start time.",
                stream_id=stream_id,
                event_id=event_id,
            ))
        uncertainty_delta = timedelta(seconds=uncertainty_seconds)
        event_start = parsed_event - uncertainty_delta
        event_end = parsed_event + uncertainty_delta
        overlapping_intervals: list[dict[str, str]] = []
        missing_intervals = stream.get("missing_intervals")
        if not isinstance(missing_intervals, list):
            raise ValidationError(f"instrument inspection record stream {stream_id} missing_intervals must be an array")
        for interval in missing_intervals:
            if not isinstance(interval, dict):
                raise ValidationError(f"instrument inspection record stream {stream_id} missing interval must be an object")
            interval_start, parsed_interval_start = _parse_time(
                interval.get("start_time"), f"record.streams.{stream_id}.missing_interval.start_time"
            )
            interval_end, parsed_interval_end = _parse_time(
                interval.get("end_time"), f"record.streams.{stream_id}.missing_interval.end_time"
            )
            if event_start <= parsed_interval_end and event_end >= parsed_interval_start:
                overlapping_intervals.append({
                    "start_time": interval_start,
                    "end_time": interval_end,
                    "reason": _text(interval.get("reason"), f"record.streams.{stream_id}.missing_interval.reason"),
                })
        event_result["overlapping_missing_intervals"] = overlapping_intervals
        if overlapping_intervals:
            findings.append(_finding(
                "EVENT_UNCERTAINTY_OVERLAPS_MISSING_INTERVAL",
                "The event's uncertainty interval overlaps inspected missing or corrupted data.",
                stream_id=stream_id,
                event_id=event_id,
            ))
        event_results.append(event_result)

    status = "timing_feasibility_failed" if any(
        finding["severity"] == "error" for finding in findings
    ) else "timing_feasibility_passed"
    record = {
        "stream_timing_assessment_version": 1,
        "assessment_id": normalized_spec["assessment_id"],
        "inspection": {
            "sha256": retained_sha256,
            "size_bytes": len(inspection_bytes),
            "stream_count": len(streams_by_id),
            "temporal_metadata_status": temporal.get("status"),
        },
        "specification": {
            "sha256": spec_sha256,
            "size_bytes": len(spec_bytes),
            "lag_window": normalized_spec["lag_window"],
            "maximum_uncertainty_fraction": normalized_spec["maximum_uncertainty_fraction"],
        },
        "required_streams": required_stream_results,
        "events": event_results,
        "findings": findings,
        "status": status,
        "scientific_evidence_eligible": False,
        "authorized_actions": [],
        "conclusion_ceiling": (
            "Provider-free timing feasibility review from a trusted inspection record only. "
            "It does not authenticate acquisition, verify calibration or drift correction, "
            "clear a protocol gate, register a dataset, or authorize scientific evidence."
        ),
    }
    _json_safe(record)
    encoded = (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError(f"stream timing assessment output path already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{root.name}-", dir=root.parent) as temporary:
        staging = Path(temporary) / root.name
        staging.mkdir()
        (staging / "stream-timing-assessment.json").write_bytes(encoded)
        try:
            os.replace(staging, root)
        except OSError as exc:
            raise ValidationError(f"could not publish stream timing assessment atomically: {exc}") from exc
    return {
        "path": str(root),
        "assessment_id": normalized_spec["assessment_id"],
        "inspection_sha256": retained_sha256,
        "specification_sha256": spec_sha256,
        "assessment_sha256": hashlib.sha256(encoded).hexdigest(),
        "status": status,
        "finding_count": len(findings),
        "scientific_evidence_eligible": False,
    }


def verify_stream_timing_assessment_record(
    record_file: Path,
    expected_record_sha256: str,
    *,
    expected_inspection_sha256: str | None = None,
    expected_specification_sha256: str | None = None,
) -> dict[str, Any]:
    """Replay a retained stream-timing assessment record from current bytes."""
    expected_record = _sha256(expected_record_sha256, "expected_record_sha256")
    record, content, retained_sha256 = _load_json_object_and_sha256(
        record_file, "stream timing assessment record"
    )
    if retained_sha256 != expected_record:
        raise ValidationError(
            "stream timing assessment record does not match expected_record_sha256"
        )
    _exact_fields(record, _STREAM_TIMING_RECORD_FIELDS, "stream_timing record")
    if record["stream_timing_assessment_version"] != 1:
        raise ValidationError("unsupported stream timing assessment record")
    assessment_id = _stable_identifier(
        record["assessment_id"], "stream_timing record assessment_id"
    )
    inspection = record["inspection"]
    if not isinstance(inspection, dict):
        raise ValidationError("stream timing assessment inspection must be an object")
    _exact_fields(inspection, _STREAM_TIMING_INSPECTION_FIELDS, "stream_timing inspection")
    inspection_sha256 = _sha256(
        inspection["sha256"], "stream_timing inspection.sha256"
    )
    if expected_inspection_sha256 is not None and inspection_sha256 != _sha256(
        expected_inspection_sha256, "expected_inspection_sha256"
    ):
        raise ValidationError("stream timing assessment inspection SHA-256 mismatch")
    if not isinstance(inspection["size_bytes"], int) or isinstance(inspection["size_bytes"], bool) or inspection["size_bytes"] <= 0:
        raise ValidationError("stream timing assessment inspection size_bytes must be a positive integer")
    if not isinstance(inspection["stream_count"], int) or isinstance(inspection["stream_count"], bool) or inspection["stream_count"] < 0:
        raise ValidationError("stream timing assessment stream_count must be a non-negative integer")
    temporal_status = _text(
        inspection["temporal_metadata_status"],
        "stream_timing inspection.temporal_metadata_status",
    )
    if temporal_status not in {"proposed_unverified", "not_provided"}:
        raise ValidationError("stream timing assessment temporal metadata status is unsupported")
    specification = record["specification"]
    if not isinstance(specification, dict):
        raise ValidationError("stream timing assessment specification must be an object")
    _exact_fields(specification, _STREAM_TIMING_SPECIFICATION_FIELDS, "stream_timing specification")
    specification_sha256 = _sha256(
        specification["sha256"], "stream_timing specification.sha256"
    )
    if expected_specification_sha256 is not None and specification_sha256 != _sha256(
        expected_specification_sha256, "expected_specification_sha256"
    ):
        raise ValidationError("stream timing assessment specification SHA-256 mismatch")
    if not isinstance(specification["size_bytes"], int) or isinstance(specification["size_bytes"], bool) or specification["size_bytes"] <= 0:
        raise ValidationError("stream timing assessment specification size_bytes must be a positive integer")
    lag_window = specification["lag_window"]
    if not isinstance(lag_window, dict):
        raise ValidationError("stream timing assessment lag_window must be an object")
    _exact_fields(lag_window, {"duration", "unit", "seconds", "basis"}, "stream_timing lag_window")
    _positive_number(lag_window["duration"], "stream_timing lag_window.duration")
    _positive_number(lag_window["seconds"], "stream_timing lag_window.seconds")
    _text(lag_window["unit"], "stream_timing lag_window.unit")
    _text(lag_window["basis"], "stream_timing lag_window.basis")
    maximum_uncertainty_fraction = _positive_number(
        specification["maximum_uncertainty_fraction"],
        "stream_timing maximum_uncertainty_fraction",
    )
    if maximum_uncertainty_fraction > 1:
        raise ValidationError("stream timing assessment maximum_uncertainty_fraction must be at most 1")
    required_streams = record["required_streams"]
    if not isinstance(required_streams, list):
        raise ValidationError("stream timing assessment required_streams must be an array")
    for index, stream in enumerate(required_streams):
        if not isinstance(stream, dict):
            raise ValidationError(f"stream timing assessment required_streams[{index}] must be an object")
        stream_id = _stable_identifier(
            stream.get("stream_id"), f"stream_timing required_streams[{index}].stream_id"
        )
        _text(stream.get("channel"), f"stream_timing required_streams[{index}].channel")
        _text(stream.get("purpose"), f"stream_timing required_streams[{index}].purpose")
        status = _text(stream.get("status"), f"stream_timing required_streams[{index}].status")
        if status not in {"present", "absent", "channel_mismatch"}:
            raise ValidationError("stream timing assessment required stream status is unsupported")
        if status != "absent":
            _text(
                stream.get("observed_channel"),
                f"stream_timing required_streams[{index}].observed_channel",
            )
        if stream_id == "":
            raise ValidationError("stream timing assessment stream_id must be non-empty")
    events = record["events"]
    if not isinstance(events, list):
        raise ValidationError("stream timing assessment events must be an array")
    event_statuses: list[str] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValidationError(f"stream timing assessment events[{index}] must be an object")
        _stable_identifier(event.get("event_id"), f"stream_timing events[{index}].event_id")
        _stable_identifier(event.get("stream_id"), f"stream_timing events[{index}].stream_id")
        _parse_time(event.get("event_time"), f"stream_timing events[{index}].event_time")
        status = _text(event.get("status"), f"stream_timing events[{index}].status")
        if status not in {
            "assessed",
            "stream_absent",
            "unsupported_uncertainty_unit",
        }:
            raise ValidationError("stream timing assessment event status is unsupported")
        event_statuses.append(status)
        if status == "assessed":
            _nonnegative_number(
                event.get("clock_uncertainty_seconds"),
                f"stream_timing events[{index}].clock_uncertainty_seconds",
            )
            _nonnegative_number(
                event.get("uncertainty_fraction_of_lag_window"),
                f"stream_timing events[{index}].uncertainty_fraction_of_lag_window",
            )
            overlaps = event.get("overlapping_missing_intervals")
            if not isinstance(overlaps, list):
                raise ValidationError("stream timing assessment overlapping_missing_intervals must be an array")
    findings = record["findings"]
    if not isinstance(findings, list):
        raise ValidationError("stream timing assessment findings must be an array")
    error_findings = 0
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise ValidationError(f"stream timing assessment findings[{index}] must be an object")
        severity = _text(
            finding.get("severity"), f"stream_timing findings[{index}].severity"
        )
        if severity not in {"warning", "error"}:
            raise ValidationError("stream timing assessment finding severity is unsupported")
        _text(finding.get("code"), f"stream_timing findings[{index}].code")
        _text(finding.get("message"), f"stream_timing findings[{index}].message")
        if severity == "error":
            error_findings += 1
    status = _text(record["status"], "stream_timing record status")
    if status not in {"timing_feasibility_passed", "timing_feasibility_failed"}:
        raise ValidationError("stream timing assessment status is unsupported")
    if record["scientific_evidence_eligible"] is not False:
        raise ValidationError("stream timing assessment must remain non-evidentiary")
    if record["authorized_actions"] != []:
        raise ValidationError("stream timing assessment must not authorize actions")
    _text(record["conclusion_ceiling"], "stream_timing conclusion_ceiling")
    failed_event = any(
        value in {"stream_absent", "unsupported_uncertainty_unit"}
        for value in event_statuses
    )
    if status == "timing_feasibility_passed" and (error_findings or failed_event):
        raise ValidationError("passed stream timing assessment record contains failures")
    if status == "timing_feasibility_failed" and not (error_findings or failed_event):
        raise ValidationError("failed stream timing assessment record lacks failed checks")
    return {
        "status": "stream_timing_assessment_record_verified",
        "record_sha256": retained_sha256,
        "record_size_bytes": len(content),
        "assessment_id": assessment_id,
        "record_status": status,
        "inspection_sha256": inspection_sha256,
        "specification_sha256": specification_sha256,
        "required_stream_count": len(required_streams),
        "event_count": len(events),
        "finding_count": len(findings),
        "scientific_evidence_eligible": False,
    }


def verify_instrument_inspection_record(
    record_file: Path,
    expected_record_sha256: str,
    *,
    expected_source_sha256: str | None = None,
    expected_config_sha256: str | None = None,
    expected_implementation_sha256: str | None = None,
) -> dict[str, Any]:
    """Replay a retained instrument-inspection record from current bytes."""
    expected_record = _sha256(expected_record_sha256, "expected_record_sha256")
    record, content, retained_sha256 = _load_json_object_and_sha256(
        record_file, "instrument inspection record"
    )
    if retained_sha256 != expected_record:
        raise ValidationError(
            "instrument inspection record does not match expected_record_sha256"
        )
    _exact_fields(record, _INSTRUMENT_INSPECTION_RECORD_FIELDS, "record")
    if record["instrument_inspection_version"] != 1:
        raise ValidationError("unsupported instrument inspection record")

    adapter = record["adapter"]
    if not isinstance(adapter, dict):
        raise ValidationError("instrument inspection adapter must be an object")
    _exact_fields(adapter, _INSTRUMENT_ADAPTER_FIELDS, "adapter")
    _text(adapter["addon_id"], "adapter.addon_id")
    _text(adapter["addon_version"], "adapter.addon_version")
    adapter_id = _stable_identifier(adapter["adapter_id"], "adapter.adapter_id")
    if adapter["authority"] != "acquisition_metadata_proposal_only":
        raise ValidationError("instrument inspection adapter authority is unsupported")
    implementation = adapter["implementation"]
    if not isinstance(implementation, dict):
        raise ValidationError("instrument inspection implementation must be an object")
    _exact_fields(implementation, _INSTRUMENT_IMPLEMENTATION_FIELDS, "implementation")
    _text(implementation["locator"], "implementation.locator")
    implementation_sha256 = _sha256(
        implementation["sha256"], "implementation.sha256"
    )
    if (
        expected_implementation_sha256 is not None
        and implementation_sha256
        != _sha256(expected_implementation_sha256, "expected_implementation_sha256")
    ):
        raise ValidationError("instrument inspection implementation SHA-256 mismatch")
    if (
        not isinstance(implementation["size_bytes"], int)
        or isinstance(implementation["size_bytes"], bool)
        or implementation["size_bytes"] <= 0
    ):
        raise ValidationError("instrument inspection implementation size_bytes must be a positive integer")

    source = record["source"]
    if not isinstance(source, dict):
        raise ValidationError("instrument inspection source must be an object")
    _exact_fields(source, _INSTRUMENT_SOURCE_FIELDS, "source")
    source_locator = _text(source["locator"], "source.locator")
    source_sha256 = _sha256(source["sha256"], "source.sha256")
    if expected_source_sha256 is not None and source_sha256 != _sha256(
        expected_source_sha256, "expected_source_sha256"
    ):
        raise ValidationError("instrument inspection source SHA-256 mismatch")
    if (
        not isinstance(source["size_bytes"], int)
        or isinstance(source["size_bytes"], bool)
        or source["size_bytes"] < 0
    ):
        raise ValidationError("instrument inspection source size_bytes must be a non-negative integer")
    _text(source["media_type"], "source.media_type")

    config = record["config"]
    if not isinstance(config, dict):
        raise ValidationError("instrument inspection config must be an object")
    _json_safe(config)
    config_sha256 = _canonical_payload_sha256(config)
    if expected_config_sha256 is not None and config_sha256 != _sha256(
        expected_config_sha256, "expected_config_sha256"
    ):
        raise ValidationError("instrument inspection config SHA-256 mismatch")

    proposed_raw_source = record["proposed_raw_source"]
    if not isinstance(proposed_raw_source, dict):
        raise ValidationError("instrument inspection proposed_raw_source must be an object")
    _exact_fields(
        proposed_raw_source,
        _INSTRUMENT_PROPOSED_RAW_SOURCE_FIELDS,
        "proposed_raw_source",
    )
    if _text(proposed_raw_source["locator"], "proposed_raw_source.locator") != source_locator:
        raise ValidationError("instrument inspection proposed raw source locator disagrees with source")
    if _sha256(proposed_raw_source["sha256"], "proposed_raw_source.sha256") != source_sha256:
        raise ValidationError("instrument inspection proposed raw source SHA-256 disagrees with source")
    _parse_time(proposed_raw_source["captured_at"], "proposed_raw_source.captured_at")
    _text(proposed_raw_source["acquisition_method"], "proposed_raw_source.acquisition_method")

    instrument = record["instrument"]
    if not isinstance(instrument, dict):
        raise ValidationError("instrument inspection instrument must be an object")
    _exact_fields(instrument, _INSTRUMENT_FIELDS, "instrument")
    _text(instrument["identifier"], "instrument.identifier")
    _text(instrument["model"], "instrument.model")
    _text(instrument["firmware_version"], "instrument.firmware_version", optional=True)
    basis = _text(instrument["captured_at_basis"], "instrument.captured_at_basis")
    if basis not in _TIME_BASES:
        raise ValidationError("instrument inspection captured_at_basis is unsupported")
    native_metadata = instrument["native_metadata"]
    if not isinstance(native_metadata, dict):
        raise ValidationError("instrument inspection native_metadata must be an object")
    _json_safe(native_metadata, canonical_text=True)

    temporal = record["temporal_metadata"]
    if not isinstance(temporal, dict):
        raise ValidationError("instrument inspection temporal_metadata must be an object")
    _exact_fields(temporal, _INSTRUMENT_TEMPORAL_METADATA_FIELDS, "temporal_metadata")
    temporal_status = _text(temporal["status"], "temporal_metadata.status")
    if temporal_status not in {"proposed_unverified", "not_provided"}:
        raise ValidationError("instrument inspection temporal metadata status is unsupported")
    if (
        not isinstance(temporal["stream_count"], int)
        or isinstance(temporal["stream_count"], bool)
        or temporal["stream_count"] < 0
    ):
        raise ValidationError("instrument inspection temporal_metadata.stream_count must be a non-negative integer")
    _string_list(temporal["limitations"], "temporal_metadata.limitations")

    streams = record["streams"]
    if not isinstance(streams, list):
        raise ValidationError("instrument inspection streams must be an array")
    seen_streams: set[str] = set()
    for index, stream in enumerate(streams):
        if not isinstance(stream, dict):
            raise ValidationError(f"instrument inspection streams[{index}] must be an object")
        label = f"streams[{index}]"
        _exact_fields(stream, _INSTRUMENT_STREAM_RECORD_FIELDS, label)
        stream_id = _stable_identifier(stream["stream_id"], f"{label}.stream_id")
        if stream_id in seen_streams:
            raise ValidationError("instrument inspection streams must have unique stream_id values")
        seen_streams.add(stream_id)
        _text(stream["source_device"], f"{label}.source_device")
        _text(stream["channel"], f"{label}.channel")
        _positive_number(stream["sample_rate_hz"], f"{label}.sample_rate_hz")
        _text(stream["clock_source"], f"{label}.clock_source")
        stream_start, parsed_stream_start = _parse_time(
            stream["start_time"], f"{label}.start_time"
        )
        drift = stream["clock_drift"]
        if not isinstance(drift, dict):
            raise ValidationError(f"instrument inspection {label}.clock_drift must be an object")
        _exact_fields(drift, _CLOCK_DRIFT_FIELDS, f"{label}.clock_drift")
        _finite_number(drift["estimate"], f"{label}.clock_drift.estimate")
        _nonnegative_number(drift["uncertainty"], f"{label}.clock_drift.uncertainty")
        if _text(drift["unit"], f"{label}.clock_drift.unit") not in _CLOCK_DRIFT_UNITS:
            raise ValidationError(f"instrument inspection {label}.clock_drift.unit is unsupported")
        _text(drift["basis"], f"{label}.clock_drift.basis")
        intervals = stream["missing_intervals"]
        if not isinstance(intervals, list):
            raise ValidationError(f"instrument inspection {label}.missing_intervals must be an array")
        previous_end: datetime | None = None
        for interval_index, interval in enumerate(intervals):
            if not isinstance(interval, dict):
                raise ValidationError(
                    f"instrument inspection {label}.missing_intervals[{interval_index}] must be an object"
                )
            interval_label = f"{label}.missing_intervals[{interval_index}]"
            _exact_fields(interval, _MISSING_INTERVAL_FIELDS, interval_label)
            _, parsed_start = _parse_time(interval["start_time"], f"{interval_label}.start_time")
            _, parsed_end = _parse_time(interval["end_time"], f"{interval_label}.end_time")
            if parsed_end <= parsed_start:
                raise ValidationError(
                    f"instrument inspection {interval_label}.end_time must be after start_time"
                )
            if parsed_start < parsed_stream_start:
                raise ValidationError(
                    f"instrument inspection {interval_label}.start_time must not precede stream start_time"
                )
            if previous_end is not None and parsed_start < previous_end:
                raise ValidationError(
                    f"instrument inspection {interval_label} must be ordered and non-overlapping"
                )
            previous_end = parsed_end
            _text(interval["reason"], f"{interval_label}.reason")
        _text(stream["calibration_record"], f"{label}.calibration_record")
        _string_list(stream["quality_flags"], f"{label}.quality_flags")
        if _sha256(stream["raw_file_sha256"], f"{label}.raw_file_sha256") != source_sha256:
            raise ValidationError("instrument inspection stream raw_file_sha256 disagrees with source")
        if (
            _sha256(stream["conversion_code_sha256"], f"{label}.conversion_code_sha256")
            != implementation_sha256
        ):
            raise ValidationError("instrument inspection stream conversion_code_sha256 disagrees with implementation")
    if temporal["stream_count"] != len(streams):
        raise ValidationError("instrument inspection temporal stream_count disagrees with streams")
    if temporal_status == "not_provided" and streams:
        raise ValidationError("instrument inspection not_provided temporal metadata cannot contain streams")
    if temporal_status == "proposed_unverified" and not streams:
        raise ValidationError("instrument inspection proposed temporal metadata requires streams")

    _canonical_text_list(record["warnings"], "warnings")
    record_status = _text(record["status"], "record.status")
    if record_status != "inspection_recorded":
        raise ValidationError("instrument inspection status is unsupported")
    if record["scientific_evidence_eligible"] is not False:
        raise ValidationError("instrument inspection must remain non-evidentiary")
    if record["authorized_actions"] != []:
        raise ValidationError("instrument inspection must not authorize actions")
    _text(record["conclusion_ceiling"], "conclusion_ceiling")
    return {
        "status": "instrument_inspection_record_verified",
        "record_sha256": retained_sha256,
        "record_size_bytes": len(content),
        "record_status": record_status,
        "adapter_id": adapter_id,
        "source_sha256": source_sha256,
        "config_sha256": config_sha256,
        "implementation_sha256": implementation_sha256,
        "stream_count": len(streams),
        "temporal_metadata_status": temporal_status,
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
