"""Typed source-authority metadata for registered datasets."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from research_machine.application.policies import (
    require_canonical_bounded_report_text,
    require_canonical_text,
)
from research_machine.domain.errors import ValidationError


SOURCE_AUTHORITY_TYPES = frozenset({
    "registered_experiment",
    "acquisition_addon",
    "scientific_connector",
    "manual_import",
    "external_attestation",
    "synthetic_fixture",
})
_ANCHOR_REQUIRED_TYPES = frozenset({
    "registered_experiment",
    "acquisition_addon",
    "scientific_connector",
    "external_attestation",
})
SOURCE_AUTHORITY_BOUNDARY = (
    "Source route only; not proof of source truth, custody, consent, "
    "calibration, measurement validity, or evidence eligibility."
)
INVALID_SOURCE_AUTHORITY_SUMMARY = (
    "source authority metadata invalid; source route not trusted until the "
    "dataset rigor finding is resolved"
)
_SOURCE_AUTHORITY_FIELDS = frozenset({
    "source_type",
    "source_name",
    "source_record_id",
    "retrieved_or_collected_at",
    "limitations",
    "classification_service_checked",
    "source_truth_verified",
    "custody_verified_by_source_authority",
    "evidence_eligibility_conferred",
    "authority_boundary",
})
_SERVICE_DERIVED_FIELDS = frozenset({
    "classification_service_checked",
    "source_truth_verified",
    "custody_verified_by_source_authority",
    "evidence_eligibility_conferred",
    "authority_boundary",
})


def validate_source_authority_timestamp(value: str, field: str) -> str:
    """Require a canonical ISO-8601 timestamp with an explicit UTC offset."""
    timestamp = require_canonical_text(value, field)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None:
        raise ValidationError(f"{field} must include a UTC offset")
    if "T" not in timestamp and "t" not in timestamp:
        raise ValidationError(f"{field} must include a time component")
    return timestamp


def validate_dataset_source_authority(
    value: object,
    *,
    synthetic: bool | None = None,
    allow_service_fields: bool = True,
) -> dict[str, Any]:
    """Validate a caller-declared dataset source route without upgrading authority."""

    if not isinstance(value, Mapping):
        raise ValidationError("dataset source_authority must be an object")
    unknown = sorted(set(value) - _SOURCE_AUTHORITY_FIELDS)
    if unknown:
        raise ValidationError(
            "dataset source_authority has unknown fields: " + ", ".join(unknown)
        )
    if not allow_service_fields:
        supplied = sorted(set(value) & _SERVICE_DERIVED_FIELDS)
        if supplied:
            raise ValidationError(
                "dataset source_authority service-derived fields cannot be supplied: "
                + ", ".join(supplied)
            )
    missing = {"source_type", "source_name"} - set(value)
    if missing:
        raise ValidationError(
            "dataset source_authority is missing fields: " + ", ".join(sorted(missing))
        )
    source_type = require_canonical_text(
        value["source_type"], "dataset source_authority.source_type"
    )
    if source_type not in SOURCE_AUTHORITY_TYPES:
        raise ValidationError(
            "dataset source_authority.source_type must be one of: "
            + ", ".join(sorted(SOURCE_AUTHORITY_TYPES))
        )
    if synthetic is False and source_type == "synthetic_fixture":
        raise ValidationError(
            "dataset source_authority.source_type synthetic_fixture requires synthetic dataset status"
        )
    source_name = require_canonical_bounded_report_text(
        value["source_name"], "dataset source_authority.source_name"
    )
    source_record_id_value = value.get("source_record_id", "")
    if source_record_id_value == "":
        if source_type in _ANCHOR_REQUIRED_TYPES:
            raise ValidationError(
                "dataset source_authority.source_record_id is required for "
                f"{source_type} source routes"
            )
        source_record_id = ""
    else:
        source_record_id = require_canonical_text(
            source_record_id_value,
            "dataset source_authority.source_record_id",
        )
    timestamp_value = value.get("retrieved_or_collected_at", "")
    if timestamp_value == "":
        if source_type in _ANCHOR_REQUIRED_TYPES:
            raise ValidationError(
                "dataset source_authority.retrieved_or_collected_at is required for "
                f"{source_type} source routes"
            )
        timestamp = ""
    else:
        timestamp = validate_source_authority_timestamp(
            timestamp_value,
            "dataset source_authority.retrieved_or_collected_at",
        )
    limitations_value = value.get("limitations", [])
    if not isinstance(limitations_value, list):
        raise ValidationError("dataset source_authority.limitations must be an array")
    limitations = [
        require_canonical_bounded_report_text(
            item, "dataset source_authority.limitations item"
        )
        for item in limitations_value
    ]
    if len(set(limitations)) != len(limitations):
        raise ValidationError("dataset source_authority.limitations must be unique")
    if value.get("classification_service_checked", True) is not True:
        raise ValidationError(
            "dataset source_authority.classification_service_checked is service-derived"
        )
    for field in (
        "source_truth_verified",
        "custody_verified_by_source_authority",
        "evidence_eligibility_conferred",
    ):
        if value.get(field, False) is not False:
            raise ValidationError(f"dataset source_authority.{field} must be false")
    if value.get("authority_boundary", SOURCE_AUTHORITY_BOUNDARY) != SOURCE_AUTHORITY_BOUNDARY:
        raise ValidationError(
            "dataset source_authority.authority_boundary is service-derived"
        )
    return {
        "source_type": source_type,
        "source_name": source_name,
        "source_record_id": source_record_id,
        "retrieved_or_collected_at": timestamp,
        "limitations": limitations,
        "classification_service_checked": True,
        "source_truth_verified": False,
        "custody_verified_by_source_authority": False,
        "evidence_eligibility_conferred": False,
        "authority_boundary": SOURCE_AUTHORITY_BOUNDARY,
    }


def dataset_source_authority_status(metadata: Mapping[str, object]) -> dict[str, Any]:
    """Return bounded inventory status for source-authority metadata."""

    value = metadata.get("source_authority")
    if value is None:
        return {
            "status": "not_recorded",
            "source_type": "not_recorded",
            "source_name": "",
            "source_record_id": "",
            "retrieved_or_collected_at": "",
            "classification_service_checked": False,
            "source_truth_verified": False,
            "custody_verified_by_source_authority": False,
            "evidence_eligibility_conferred": False,
            "authority_boundary": SOURCE_AUTHORITY_BOUNDARY,
            "limitations": [],
            "summary": (
                "source route not typed; artifact hashes and dataset role do not "
                "establish source authority"
            ),
        }
    try:
        authority = validate_dataset_source_authority(value)
    except ValidationError:
        return {
            "status": "invalid_metadata",
            "source_type": "invalid_metadata",
            "source_name": "",
            "source_record_id": "",
            "retrieved_or_collected_at": "",
            "classification_service_checked": False,
            "source_truth_verified": False,
            "custody_verified_by_source_authority": False,
            "evidence_eligibility_conferred": False,
            "authority_boundary": SOURCE_AUTHORITY_BOUNDARY,
            "limitations": [],
            "summary": INVALID_SOURCE_AUTHORITY_SUMMARY,
        }
    return {
        "status": "typed_source_route",
        **authority,
        "summary": (
            f"{authority['source_type']} source route `{authority['source_name']}` "
            "recorded as provenance only; connector, add-on, experiment, import, "
            "or attestation access does not confer evidence eligibility"
        ),
    }
