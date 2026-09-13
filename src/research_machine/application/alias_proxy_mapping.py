"""Custody checks for blinded alias and proxy measurement mappings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from research_machine.application.artifact_integrity import _safe_artifact_path
from research_machine.application.policies import (
    require_canonical_bounded_report_text,
    require_canonical_text,
    require_nonempty_unique_bounded_report_text_list,
    require_sha256,
)
from research_machine.application.protocol_integrity import protocol_commitment
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AliasProxyMappingEntry,
    AliasProxyMappingRecord,
    ExperimentProtocol,
    MeasurementDefinition,
    ProtocolStatus,
)


ALIAS_PROXY_MAPPING_CONCLUSION_CEILING = (
    "Private alias/proxy mapping bytes match the frozen protocol commitment; "
    "this does not reveal the mapping, prove construct validity, authenticate "
    "the mapper, establish ethics compliance, or authorize evidence by itself."
)


def _mapping_set_sha256(entries: list[AliasProxyMappingEntry]) -> str:
    payload = [
        {
            "measurement_id": entry.measurement_id,
            "commitment_id": entry.commitment_id,
            "mapping_locator": entry.mapping_locator,
            "mapping_sha256": entry.mapping_sha256,
            "mapping_size_bytes": entry.mapping_size_bytes,
            "media_type": entry.media_type,
        }
        for entry in entries
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def alias_proxy_commitments(
    protocol: ExperimentProtocol,
) -> list[tuple[MeasurementDefinition, Any]]:
    return [
        (definition, definition.alias_proxy_commitment)
        for definition in protocol.measurement_definitions
        if definition.alias_proxy_commitment is not None
    ]


def protocol_requires_alias_proxy_mapping(protocol: ExperimentProtocol) -> bool:
    return bool(alias_proxy_commitments(protocol))


def validate_alias_proxy_mapping_record(
    protocol: ExperimentProtocol,
    record: AliasProxyMappingRecord,
    *,
    verify_current_artifacts: bool = True,
) -> AliasProxyMappingRecord:
    if protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash:
        raise ValidationError("alias/proxy mapping custody requires a frozen protocol")
    if protocol_commitment(protocol) != protocol.protocol_hash:
        raise ValidationError("frozen protocol content no longer matches its hash commitment")
    require_canonical_text(record.record_id, "alias mapping record_id")
    if record.protocol_id != protocol.protocol_id:
        raise ValidationError("alias mapping record is bound to a different protocol")
    if record.protocol_hash != protocol.protocol_hash:
        raise ValidationError("alias mapping record protocol_hash does not match the frozen protocol")
    require_canonical_text(record.created_at, "alias mapping created_at")
    require_canonical_text(record.created_by, "alias mapping created_by")
    require_canonical_text(
        record.mapping_artifact_root, "alias mapping artifact root"
    )
    require_canonical_bounded_report_text(
        record.access_control_statement,
        "alias mapping access_control_statement",
    )
    require_canonical_bounded_report_text(
        record.reveal_policy_statement,
        "alias mapping reveal_policy_statement",
    )
    require_nonempty_unique_bounded_report_text_list(
        record.limitations,
        "alias mapping limitations",
    )
    if record.conclusion_ceiling != ALIAS_PROXY_MAPPING_CONCLUSION_CEILING:
        raise ValidationError("alias mapping conclusion_ceiling changed")
    if record.scientific_interpretation_verified is not False:
        raise ValidationError(
            "alias mapping custody cannot verify scientific interpretation"
        )

    commitments = {
        (definition.measurement_id, commitment.commitment_id): (
            definition,
            commitment,
        )
        for definition, commitment in alias_proxy_commitments(protocol)
    }
    if not commitments:
        raise ValidationError("protocol has no alias/proxy commitments to verify")
    if len(commitments) != len(alias_proxy_commitments(protocol)):
        raise ValidationError(
            "alias/proxy commitment IDs must be unique per measurement"
        )
    observed_keys: set[tuple[str, str]] = set()
    normalized_entries: list[AliasProxyMappingEntry] = []
    root = Path(record.mapping_artifact_root).expanduser().resolve()
    if verify_current_artifacts and (not root.is_dir() or root.is_symlink()):
        raise ValidationError("alias mapping artifact root is unavailable or unsafe")
    for index, entry in enumerate(record.mappings):
        prefix = f"alias mapping entry {index}"
        measurement_id = require_canonical_text(
            entry.measurement_id, f"{prefix} measurement_id"
        )
        commitment_id = require_canonical_text(
            entry.commitment_id, f"{prefix} commitment_id"
        )
        key = (measurement_id, commitment_id)
        if key in observed_keys:
            raise ValidationError("alias mapping entries repeat a measurement commitment")
        observed_keys.add(key)
        if key not in commitments:
            raise ValidationError(
                "alias mapping entry does not match any frozen alias/proxy commitment"
            )
        _definition, commitment = commitments[key]
        mapping_sha256 = require_sha256(
            entry.mapping_sha256, f"{prefix} mapping_sha256"
        )
        if mapping_sha256 != commitment.private_mapping_sha256:
            raise ValidationError(
                "alias mapping bytes do not match the frozen private mapping commitment"
            )
        locator = require_canonical_text(
            entry.mapping_locator, f"{prefix} mapping_locator"
        )
        media_type = require_canonical_text(entry.media_type, f"{prefix} media_type")
        if (
            isinstance(entry.mapping_size_bytes, bool)
            or not isinstance(entry.mapping_size_bytes, int)
            or entry.mapping_size_bytes < 0
        ):
            raise ValidationError(f"{prefix} mapping_size_bytes must be non-negative")
        if verify_current_artifacts:
            path, unsafe = _safe_artifact_path(root, locator)
            if unsafe is not None or path is None:
                raise ValidationError(
                    f"{prefix} mapping locator is unsafe or escapes the artifact root"
                )
            if not path.is_file() or path.is_symlink():
                raise ValidationError(f"{prefix} mapping file is unavailable")
            content = path.read_bytes()
            observed_sha256 = hashlib.sha256(content).hexdigest()
            if observed_sha256 != mapping_sha256:
                raise ValidationError(
                    f"{prefix} current bytes do not match the frozen mapping SHA-256"
                )
            if len(content) != entry.mapping_size_bytes:
                raise ValidationError(
                    f"{prefix} current bytes do not match mapping_size_bytes"
                )
        normalized_entries.append(
            AliasProxyMappingEntry(
                measurement_id=measurement_id,
                commitment_id=commitment_id,
                mapping_locator=locator,
                mapping_sha256=mapping_sha256,
                mapping_size_bytes=entry.mapping_size_bytes,
                media_type=media_type,
            )
        )
    missing = sorted(set(commitments) - observed_keys)
    if missing:
        raise ValidationError(
            "alias mapping record lacks frozen commitments: "
            + ", ".join(f"{measurement}:{commitment}" for measurement, commitment in missing)
        )
    extra = sorted(observed_keys - set(commitments))
    if extra:
        raise ValidationError(
            "alias mapping record contains unexpected commitments: "
            + ", ".join(f"{measurement}:{commitment}" for measurement, commitment in extra)
        )
    mapping_set_sha256 = require_sha256(
        record.mapping_set_sha256,
        "alias mapping mapping_set_sha256",
    )
    expected_set_sha256 = _mapping_set_sha256(normalized_entries)
    if mapping_set_sha256 != expected_set_sha256:
        raise ValidationError("alias mapping set hash does not match its entries")
    return AliasProxyMappingRecord(
        record_id=record.record_id,
        protocol_id=protocol.protocol_id,
        protocol_hash=protocol.protocol_hash,
        created_at=record.created_at,
        created_by=record.created_by,
        mapping_artifact_root=str(root),
        mappings=normalized_entries,
        mapping_set_sha256=mapping_set_sha256,
        access_control_statement=record.access_control_statement,
        reveal_policy_statement=record.reveal_policy_statement,
        limitations=list(record.limitations),
        conclusion_ceiling=record.conclusion_ceiling,
        scientific_interpretation_verified=False,
    )


def build_alias_proxy_mapping_record(
    *,
    protocol: ExperimentProtocol,
    record_id: str,
    created_at: str,
    created_by: str,
    mapping_artifact_root: str,
    mappings: list[dict[str, Any]],
    access_control_statement: str,
    reveal_policy_statement: str,
    limitations: list[str],
) -> AliasProxyMappingRecord:
    if not isinstance(mappings, list) or any(
        not isinstance(item, dict) for item in mappings
    ):
        raise ValidationError("alias mapping mappings must be an array of objects")
    if not isinstance(limitations, list) or any(
        not isinstance(item, str) for item in limitations
    ):
        raise ValidationError("alias mapping limitations must be a list of text values")
    entries: list[AliasProxyMappingEntry] = []
    for index, item in enumerate(mappings):
        missing = [
            field
            for field in ("measurement_id", "commitment_id", "mapping_locator")
            if field not in item
        ]
        if missing:
            raise ValidationError(
                f"alias mapping entry {index} lacks fields: {', '.join(missing)}"
            )
        mapping_size_bytes = item.get("mapping_size_bytes", -1)
        if isinstance(mapping_size_bytes, bool) or not isinstance(
            mapping_size_bytes, int
        ):
            raise ValidationError(
                f"alias mapping entry {index} mapping_size_bytes must be an integer"
            )
        entries.append(
            AliasProxyMappingEntry(
                measurement_id=item["measurement_id"],
                commitment_id=item["commitment_id"],
                mapping_locator=item["mapping_locator"],
                mapping_sha256=item.get("mapping_sha256", ""),
                mapping_size_bytes=mapping_size_bytes,
                media_type=item.get("media_type", "application/json"),
            )
        )
    root = Path(mapping_artifact_root).expanduser().resolve()
    hydrated_entries: list[AliasProxyMappingEntry] = []
    for entry in entries:
        path, unsafe = _safe_artifact_path(root, entry.mapping_locator)
        if unsafe is not None or path is None:
            raise ValidationError(
                "alias mapping locator is unsafe or escapes the artifact root"
            )
        if not path.is_file() or path.is_symlink():
            raise ValidationError("alias mapping file is unavailable")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if entry.mapping_sha256 and entry.mapping_sha256 != digest:
            raise ValidationError(
                "alias mapping declared SHA-256 does not match current bytes"
            )
        if entry.mapping_size_bytes not in {-1, len(content)}:
            raise ValidationError(
                "alias mapping declared size does not match current bytes"
            )
        hydrated_entries.append(
            AliasProxyMappingEntry(
                measurement_id=entry.measurement_id,
                commitment_id=entry.commitment_id,
                mapping_locator=entry.mapping_locator,
                mapping_sha256=digest,
                mapping_size_bytes=len(content),
                media_type=entry.media_type,
            )
        )
    record = AliasProxyMappingRecord(
        record_id=record_id,
        protocol_id=protocol.protocol_id,
        protocol_hash=protocol.protocol_hash or "",
        created_at=created_at,
        created_by=created_by,
        mapping_artifact_root=str(root),
        mappings=hydrated_entries,
        mapping_set_sha256=_mapping_set_sha256(hydrated_entries),
        access_control_statement=access_control_statement,
        reveal_policy_statement=reveal_policy_statement,
        limitations=list(limitations),
        conclusion_ceiling=ALIAS_PROXY_MAPPING_CONCLUSION_CEILING,
        scientific_interpretation_verified=False,
    )
    return validate_alias_proxy_mapping_record(protocol, record)
