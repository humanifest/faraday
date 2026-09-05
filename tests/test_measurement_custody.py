from __future__ import annotations

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.measurement.custody import validate_measurement_custody


def _receipt() -> dict:
    raw, derived = "a" * 64, "b" * 64
    return {
        "receipt_id": "mc-001",
        "raw_sources": [{"locator": "capture.bin", "sha256": raw, "captured_at": "2026-09-04T00:00:00Z", "acquisition_method": "instrument export"}],
        "transformations": [{"transformation_id": "events", "version": "1", "implementation_sha256": "c" * 64, "input_sha256": raw, "output_sha256": derived}],
        "calibrations": [{"calibration_id": "clock", "reference": "GPS", "performed_at": "2026-09-04T00:00:00Z", "result": "residual < 1 ms", "status": "passed"}],
        "quality_gates": [{"gate_id": "clock-sync", "status": "passed", "summary": "clock alignment passed"}],
        "derived_observations": [{"observation_id": "event", "definition": "detected event", "source_output_sha256": derived}],
    }


def test_custody_receipt_requires_lineage_calibration_and_required_gates() -> None:
    assert validate_measurement_custody(_receipt(), ["clock-sync"])["receipt_id"] == "mc-001"
    with pytest.raises(ValidationError, match="missing required gates"):
        validate_measurement_custody(_receipt(), ["sensor-validity"])


def test_custody_receipt_rejects_untraceable_derived_observation() -> None:
    receipt = _receipt()
    receipt["derived_observations"][0]["source_output_sha256"] = "d" * 64
    with pytest.raises(ValidationError, match="transformation output"):
        validate_measurement_custody(receipt)
