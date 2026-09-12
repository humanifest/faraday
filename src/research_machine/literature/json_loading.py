"""Strict JSON loading for retained literature artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from research_machine.domain.errors import ValidationError


def load_json_object(path: Path, label: str) -> tuple[dict[str, Any], str]:
    """Return a JSON object and byte digest, rejecting ambiguous JSON syntax."""
    try:
        content = path.read_bytes()
        value = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError(f"could not read valid {label} JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value, hashlib.sha256(content).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    raise ValidationError(f"non-finite JSON number is not permitted: {value}")
