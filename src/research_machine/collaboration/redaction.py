"""Shared redaction contract for provider-neutral collaboration artifacts."""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from research_machine.domain.errors import ValidationError

COLLABORATOR_CONTEXT_REDACTION_MARKER = "[redacted: retained in canonical store]"

# Version 1 replay is immutable. Keep its original exact operational-key set.
LEGACY_OPERATIONAL_CONTEXT_KEYS = {
    "artifact_root",
    "attestation_schema_path",
    "custody_artifact_root",
    "ethics_artifact_root",
    "origin_artifact_root",
    "review_artifact_root",
    "run_artifact_root",
    "run_attestation_schema_path",
}
OPERATIONAL_CONTEXT_KEYS = LEGACY_OPERATIONAL_CONTEXT_KEYS | {
    "current_synthesis_path",
    "evidence_artifact_root",
    "interpreter_path",
}

JSON_SELECTOR_KEYS = {
    "effect_estimate_path",
    "evidence_location",
    "p_value_path",
    "uncertainty_path",
}
HOST_IDENTITY_KEYS = {
    "home",
    "home_dir",
    "host",
    "host_id",
    "host_name",
    "hostname",
    "machine_name",
    "user_id",
    "user_name",
    "username",
}
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_PLATFORM_ROOT_SEGMENTS = {
    "etc",
    "home",
    "mnt",
    "opt",
    "private",
    "tmp",
    "users",
    "usr",
    "var",
    "volumes",
    "workspace",
}
_METADATA_LOCATION_KEYS = {
    "directory",
    "directories",
    "file",
    "files",
    "location",
    "locations",
    "locator",
    "locators",
    "path",
    "paths",
    "root",
    "roots",
    "uri",
    "uris",
}


def contains_forbidden_control(value: object) -> bool:
    """Return whether text contains a C0 or DEL control character."""
    return isinstance(value, str) and any(
        ord(character) <= 0x1F or ord(character) == 0x7F for character in value
    )


def is_safe_logical_locator(value: object) -> bool:
    """Accept only canonical, non-traversing, portable relative locators."""
    if value == COLLABORATOR_CONTEXT_REDACTION_MARKER:
        return True
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if (
        contains_forbidden_control(value)
        or "%" in value
        or "\\" in value
        or value.startswith("~")
    ):
        return False
    windows_path = PureWindowsPath(value)
    if PurePosixPath(value).is_absolute() or windows_path.is_absolute() or windows_path.drive:
        return False
    if _URI_SCHEME.match(value):
        return False
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    if any(part.casefold() in _PLATFORM_ROOT_SEGMENTS for part in parts):
        return False
    return not any(part.casefold().endswith(".local") for part in parts)


def is_typed_metadata_location_key(key: object) -> bool:
    if not isinstance(key, str) or key in JSON_SELECTOR_KEYS:
        return False
    return key in _METADATA_LOCATION_KEYS or any(
        key.endswith(f"_{suffix}") for suffix in _METADATA_LOCATION_KEYS
    )


def _locator_value(
    value: Any,
    *,
    force_redaction: bool,
) -> Any:
    if force_redaction or not is_safe_logical_locator(value):
        return COLLABORATOR_CONTEXT_REDACTION_MARKER
    return value


def redact_collaborator_context(
    value: Any,
    *,
    _context_root: bool = True,
    _dataset_record: bool = False,
    _dataset_artifact: bool = False,
    _metadata: bool = False,
) -> Any:
    """Create a deterministic v2 projection without changing canonical state."""
    if isinstance(value, list):
        return [
            redact_collaborator_context(
                item,
                _context_root=False,
                _dataset_record=_dataset_record,
                _dataset_artifact=_dataset_artifact,
                _metadata=_metadata,
            )
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    projected: dict[str, Any] = {}
    for key, item in value.items():
        if _dataset_artifact and _metadata and contains_forbidden_control(key):
            raise ValidationError(
                "collaborator dataset artifact metadata property names must not "
                "contain C0 or DEL control characters"
            )
        if key in OPERATIONAL_CONTEXT_KEYS:
            if _dataset_artifact and _metadata and is_typed_metadata_location_key(key):
                projected[key] = COLLABORATOR_CONTEXT_REDACTION_MARKER
            else:
                projected[key] = (
                    None
                    if key == "current_synthesis_path" and item is None
                    else COLLABORATOR_CONTEXT_REDACTION_MARKER
                )
        elif key in HOST_IDENTITY_KEYS:
            projected[key] = (
                item
                if item in (None, "")
                else COLLABORATOR_CONTEXT_REDACTION_MARKER
            )
        elif key in JSON_SELECTOR_KEYS:
            projected[key] = item
        elif _context_root and key == "datasets" and isinstance(item, list):
            projected[key] = [
                redact_collaborator_context(
                    entry,
                    _context_root=False,
                    _dataset_record=True,
                )
                for entry in item
            ]
        elif _dataset_record and key == "artifacts" and isinstance(item, list):
            projected[key] = [
                redact_collaborator_context(
                    entry,
                    _context_root=False,
                    _dataset_artifact=True,
                )
                for entry in item
            ]
        elif (
            _dataset_artifact
            and _metadata
            and is_typed_metadata_location_key(key)
        ):
            projected[key] = COLLABORATOR_CONTEXT_REDACTION_MARKER
        elif key == "locator" or key.endswith("_locator"):
            projected[key] = _locator_value(
                item,
                force_redaction=_dataset_artifact,
            )
        elif key == "locators" or key.endswith("_locators"):
            projected[key] = [
                _locator_value(
                    entry,
                    force_redaction=_dataset_artifact,
                )
                for entry in item
            ] if isinstance(item, list) else COLLABORATOR_CONTEXT_REDACTION_MARKER
        elif key == "path" or key.endswith("_path") or key.endswith("_root"):
            if _dataset_artifact:
                projected[key] = COLLABORATOR_CONTEXT_REDACTION_MARKER
            elif not item or is_safe_logical_locator(item):
                projected[key] = item
            else:
                projected[key] = COLLABORATOR_CONTEXT_REDACTION_MARKER
        else:
            projected[key] = redact_collaborator_context(
                item,
                _context_root=False,
                _dataset_artifact=_dataset_artifact,
                _metadata=_metadata or key == "metadata",
            )
    return projected
