"""Shared redaction contract for provider-neutral collaboration artifacts."""

from __future__ import annotations

import re
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

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
    "host_name",
    "hostname",
    "machine_name",
    "user_name",
    "username",
}
_HOST_LOCATION = re.compile(
    r"(?:(?:file|nfs|smb|ssh):|(?<!:)//[^/\s]+/|\\\\[^\\\s]+\\|"
    r"(?<![:/A-Za-z0-9])/(?:$|(?:[^/\s]+/)*[^/\s]+)|"
    r"(?<![A-Za-z0-9])[A-Za-z]:(?:$|[\\/]|[^\s:]+)|(?<![A-Za-z0-9])~(?:$|[\\/])|"
    r"(?<![A-Za-z0-9+.-])(?!https?://)(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9._-]+:/|"
    r"\b(?:localhost|[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.local)\b)"
)
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_ESCAPED_TRAVERSAL = re.compile(r"%(?:2e|2f|5c)", re.IGNORECASE)


def contains_forbidden_control(value: object) -> bool:
    """Return whether text contains a C0 or DEL control character."""
    return isinstance(value, str) and any(
        ord(character) <= 0x1F or ord(character) == 0x7F for character in value
    )


def contains_host_location(value: object) -> bool:
    """Return whether text exposes an absolute or host-specific file location."""
    if not isinstance(value, str) or value == COLLABORATOR_CONTEXT_REDACTION_MARKER:
        return False
    return bool(_HOST_LOCATION.search(value) or _ESCAPED_TRAVERSAL.search(value))


def is_safe_logical_locator(value: object) -> bool:
    """Accept only canonical, non-traversing, portable relative locators."""
    if value == COLLABORATOR_CONTEXT_REDACTION_MARKER:
        return True
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if contains_forbidden_control(value) or "\\" in value or value.startswith("~"):
        return False
    windows_path = PureWindowsPath(value)
    if PurePosixPath(value).is_absolute() or windows_path.is_absolute() or windows_path.drive:
        return False
    if _URI_SCHEME.match(value) or _ESCAPED_TRAVERSAL.search(value):
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def is_verified_workspace_locator(
    value: object, workspace_root: str | Path | None
) -> bool:
    """No-follow verify an already-relative regular file below the workspace."""
    if (
        value == COLLABORATOR_CONTEXT_REDACTION_MARKER
        or not is_safe_logical_locator(value)
        or workspace_root is None
    ):
        return False
    try:
        root = Path(workspace_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    candidate = root
    parts = str(value).split("/")
    for index, part in enumerate(parts):
        candidate = candidate / part
        try:
            mode = candidate.lstat().st_mode
        except OSError:
            return False
        if stat.S_ISLNK(mode):
            return False
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            return False
    return stat.S_ISREG(mode)


def _locator_value(
    value: Any,
    *,
    workspace_root: str | Path | None,
    verify_workspace: bool,
) -> Any:
    if not isinstance(value, str):
        return redact_collaborator_context(value, workspace_root=workspace_root)
    safe = (
        is_verified_workspace_locator(value, workspace_root)
        if verify_workspace
        else is_safe_logical_locator(value)
    )
    return value if safe else COLLABORATOR_CONTEXT_REDACTION_MARKER


def redact_collaborator_context(
    value: Any,
    *,
    workspace_root: str | Path | None = None,
    _dataset_artifact: bool = False,
) -> Any:
    """Create a deterministic v2 projection without changing canonical state."""
    if isinstance(value, list):
        return [
            redact_collaborator_context(
                item,
                workspace_root=workspace_root,
                _dataset_artifact=_dataset_artifact,
            )
            for item in value
        ]
    if not isinstance(value, dict):
        if contains_forbidden_control(value) or contains_host_location(value):
            return COLLABORATOR_CONTEXT_REDACTION_MARKER
        return value

    projected: dict[str, Any] = {}
    for key, item in value.items():
        # User metadata can place host paths in keys; omit those fields rather than
        # inventing a collision-prone basename or provenance label.
        if contains_forbidden_control(key) or contains_host_location(key):
            continue
        if key in OPERATIONAL_CONTEXT_KEYS:
            projected[key] = (
                COLLABORATOR_CONTEXT_REDACTION_MARKER if item else item
            )
        elif key in HOST_IDENTITY_KEYS:
            projected[key] = (
                COLLABORATOR_CONTEXT_REDACTION_MARKER if item else item
            )
        elif key in JSON_SELECTOR_KEYS:
            projected[key] = (
                COLLABORATOR_CONTEXT_REDACTION_MARKER
                if contains_forbidden_control(item)
                else item
            )
        elif key == "locator" or key.endswith("_locator"):
            projected[key] = _locator_value(
                item,
                workspace_root=workspace_root,
                verify_workspace=_dataset_artifact,
            )
        elif key == "locators" or key.endswith("_locators"):
            projected[key] = [
                _locator_value(
                    entry,
                    workspace_root=workspace_root,
                    verify_workspace=_dataset_artifact,
                )
                for entry in item
            ] if isinstance(item, list) else COLLABORATOR_CONTEXT_REDACTION_MARKER
        elif key == "path" or key.endswith("_path") or key.endswith("_root"):
            safe = (
                is_verified_workspace_locator(item, workspace_root)
                if _dataset_artifact and item
                else is_safe_logical_locator(item)
            )
            projected[key] = (
                item
                if not item or safe
                else COLLABORATOR_CONTEXT_REDACTION_MARKER
            )
        elif key == "artifacts" and isinstance(item, list) and "dataset_id" in value:
            projected[key] = [
                redact_collaborator_context(
                    entry,
                    workspace_root=workspace_root,
                    _dataset_artifact=True,
                )
                for entry in item
            ]
        elif contains_forbidden_control(item) or contains_host_location(item):
            projected[key] = COLLABORATOR_CONTEXT_REDACTION_MARKER
        else:
            projected[key] = redact_collaborator_context(
                item,
                workspace_root=workspace_root,
                _dataset_artifact=_dataset_artifact,
            )
    return projected
