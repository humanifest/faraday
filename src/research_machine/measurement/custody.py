from __future__ import annotations

from typing import Any, Sequence

from research_machine.domain.errors import ValidationError


_HEX = set("0123456789abcdef")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"measurement custody {field} must be non-empty text")
    return value


def _digest(value: Any, field: str) -> str:
    value = _text(value, field)
    if len(value) != 64 or set(value) - _HEX:
        raise ValidationError(f"measurement custody {field} must be a lowercase SHA-256")
    return value


def validate_measurement_custody(
    receipt: Any, required_gate_ids: Sequence[str] = ()
) -> dict[str, Any]:
    """Require a fully traceable raw-to-derived measurement chain."""
    if not isinstance(receipt, dict):
        raise ValidationError("measurement_custody metadata must be an object")
    allowed = {
        "receipt_id",
        "raw_sources",
        "transformations",
        "calibrations",
        "quality_gates",
        "derived_observations",
    }
    unknown = sorted(set(receipt) - allowed)
    if unknown:
        raise ValidationError("unknown measurement custody fields: " + ", ".join(unknown))
    _text(receipt.get("receipt_id"), "receipt_id")
    sources = receipt.get("raw_sources")
    if not isinstance(sources, list) or not sources:
        raise ValidationError("measurement custody raw_sources must be a non-empty array")
    hashes: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValidationError("each raw source must be an object")
        for field in ("locator", "captured_at", "acquisition_method"):
            _text(source.get(field), f"raw_sources[{index}].{field}")
        hashes.add(_digest(source.get("sha256"), f"raw_sources[{index}].sha256"))
    transformations = receipt.get("transformations")
    if not isinstance(transformations, list) or not transformations:
        raise ValidationError("measurement custody transformations must be a non-empty array")
    outputs: set[str] = set()
    for index, item in enumerate(transformations):
        if not isinstance(item, dict):
            raise ValidationError("each transformation must be an object")
        for field in ("transformation_id", "version"):
            _text(item.get(field), f"transformations[{index}].{field}")
        _digest(
            item.get("implementation_sha256"),
            f"transformations[{index}].implementation_sha256",
        )
        source = _digest(item.get("input_sha256"), f"transformations[{index}].input_sha256")
        output = _digest(item.get("output_sha256"), f"transformations[{index}].output_sha256")
        if source not in hashes | outputs:
            raise ValidationError(
                "transformation input_sha256 must be a raw source or prior "
                "transformation output"
            )
        outputs.add(output)
    calibrations = receipt.get("calibrations")
    if not isinstance(calibrations, list) or not calibrations:
        raise ValidationError("measurement custody calibrations must be a non-empty array")
    for item in calibrations:
        if not isinstance(item, dict):
            raise ValidationError("each calibration must be an object")
        for field in ("calibration_id", "reference", "performed_at", "result"):
            _text(item.get(field), f"calibration.{field}")
        if item.get("status") != "passed":
            raise ValidationError("measurement custody calibration status must be passed")
    gates = receipt.get("quality_gates")
    if not isinstance(gates, list) or not gates:
        raise ValidationError("measurement custody quality_gates must be a non-empty array")
    gate_ids: set[str] = set()
    for item in gates:
        if not isinstance(item, dict):
            raise ValidationError("each measurement quality gate must be an object")
        gate_id = _text(item.get("gate_id"), "quality gate gate_id")
        if gate_id in gate_ids:
            raise ValidationError(f"duplicate measurement quality gate: {gate_id}")
        gate_ids.add(gate_id)
        _text(item.get("summary"), f"quality gate {gate_id} summary")
        if item.get("status") != "passed":
            raise ValidationError(
                f"measurement quality gate {gate_id} must be passed"
            )
    missing = sorted(set(required_gate_ids) - gate_ids)
    if missing:
        raise ValidationError("measurement custody is missing required gates: " + ", ".join(missing))
    observations = receipt.get("derived_observations")
    if not isinstance(observations, list) or not observations:
        raise ValidationError("measurement custody derived_observations must be a non-empty array")
    for item in observations:
        if not isinstance(item, dict):
            raise ValidationError("each derived observation must be an object")
        _text(item.get("observation_id"), "derived observation observation_id")
        _text(item.get("definition"), "derived observation definition")
        output = _digest(
            item.get("source_output_sha256"),
            "derived observation source_output_sha256",
        )
        if output not in outputs:
            raise ValidationError("derived observation source_output_sha256 must be a transformation output")
    return receipt
