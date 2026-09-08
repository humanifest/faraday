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
_ABSOLUTE_TIME_UNITS_TO_SECONDS = {
    "s": 1.0,
    "ms": 0.001,
    "us": 0.000001,
    "ns": 0.000000001,
}


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
