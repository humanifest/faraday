"""Fail-closed validation for the JSON Schema subset used by attestations.

This is deliberately not advertised as a complete JSON Schema implementation.
It supports a pinned Draft 2020-12 profile and rejects schemas containing
keywords outside that profile, so an unsupported constraint can never be
silently ignored during replication intake.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any


_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_SUPPORTED_KEYWORDS = {
    "$schema",
    "$id",
    "$defs",
    "$ref",
    "title",
    "description",
    "type",
    "required",
    "properties",
    "additionalProperties",
    "const",
    "enum",
    "minLength",
    "pattern",
    "format",
    "minItems",
    "uniqueItems",
    "allOf",
    "contains",
    "items",
    "not",
}
_SCHEMA_MAP_KEYWORDS = {"properties", "$defs"}
_SCHEMA_SINGLE_KEYWORDS = {"additionalProperties", "contains", "items", "not"}


class AttestationSchemaProfileError(ValueError):
    """Raised when a schema cannot be interpreted by the pinned profile."""


def _json_path(parts: list[str | int]) -> str:
    if not parts:
        return "$"
    result = "$"
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part):
            result += f".{part}"
        else:
            result += f"[{json.dumps(part)}]"
    return result


def _check_schema_shape(schema: Any, *, path: list[str | int]) -> None:
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise AttestationSchemaProfileError(
            f"schema at {_json_path(path)} must be an object or boolean"
        )
    unsupported = sorted(set(schema) - _SUPPORTED_KEYWORDS)
    if unsupported:
        raise AttestationSchemaProfileError(
            f"schema at {_json_path(path)} uses unsupported keywords: "
            + ", ".join(unsupported)
        )
    if "$schema" in schema and schema["$schema"] != _DRAFT_2020_12:
        raise AttestationSchemaProfileError(
            f"schema at {_json_path(path)} must declare Draft 2020-12"
        )
    for keyword in _SCHEMA_MAP_KEYWORDS:
        if keyword not in schema:
            continue
        value = schema[keyword]
        if not isinstance(value, dict):
            raise AttestationSchemaProfileError(
                f"{keyword} at {_json_path(path)} must be an object"
            )
        for name, child in value.items():
            _check_schema_shape(child, path=[*path, keyword, name])
    for keyword in _SCHEMA_SINGLE_KEYWORDS:
        if keyword not in schema:
            continue
        child = schema[keyword]
        if keyword == "additionalProperties" and not isinstance(child, (dict, bool)):
            raise AttestationSchemaProfileError(
                f"additionalProperties at {_json_path(path)} must be a schema"
            )
        _check_schema_shape(child, path=[*path, keyword])
    if "allOf" in schema:
        all_of = schema["allOf"]
        if not isinstance(all_of, list) or not all_of:
            raise AttestationSchemaProfileError(
                f"allOf at {_json_path(path)} must be a nonempty array"
            )
        for index, child in enumerate(all_of):
            _check_schema_shape(child, path=[*path, "allOf", index])
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/"):
            raise AttestationSchemaProfileError(
                f"$ref at {_json_path(path)} must be a local JSON pointer"
            )
    if "type" in schema:
        schema_type = schema["type"]
        if schema_type not in {
            "object",
            "array",
            "string",
            "number",
            "integer",
            "boolean",
            "null",
        }:
            raise AttestationSchemaProfileError(
                f"unsupported type at {_json_path(path)}: {schema_type!r}"
            )
    if "required" in schema and (
        not isinstance(schema["required"], list)
        or any(not isinstance(item, str) for item in schema["required"])
        or len(set(schema["required"])) != len(schema["required"])
    ):
        raise AttestationSchemaProfileError(
            f"required at {_json_path(path)} must be an array of unique strings"
        )
    for keyword in ("minLength", "minItems"):
        if keyword in schema and (
            not isinstance(schema[keyword], int)
            or isinstance(schema[keyword], bool)
            or schema[keyword] < 0
        ):
            raise AttestationSchemaProfileError(
                f"{keyword} at {_json_path(path)} must be a non-negative integer"
            )
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        raise AttestationSchemaProfileError(
            f"uniqueItems at {_json_path(path)} must be boolean"
        )
    if "enum" in schema and not isinstance(schema["enum"], list):
        raise AttestationSchemaProfileError(
            f"enum at {_json_path(path)} must be an array"
        )
    if "pattern" in schema:
        if not isinstance(schema["pattern"], str):
            raise AttestationSchemaProfileError(
                f"pattern at {_json_path(path)} must be a string"
            )
        try:
            re.compile(schema["pattern"])
        except (TypeError, re.error) as exc:
            raise AttestationSchemaProfileError(
                f"invalid pattern at {_json_path(path)}: {exc}"
            ) from exc
    if "format" in schema and schema["format"] != "date-time":
        raise AttestationSchemaProfileError(
            f"unsupported format at {_json_path(path)}: {schema['format']!r}"
        )


def _resolve_local_reference(root: dict[str, Any], reference: str) -> Any:
    current: Any = root
    for encoded_part in reference[2:].split("/"):
        part = encoded_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise AttestationSchemaProfileError(
                f"unresolved local schema reference: {reference}"
            )
        current = current[part]
    if not isinstance(current, (dict, bool)):
        raise AttestationSchemaProfileError(
            f"local schema reference does not resolve to a schema: {reference}"
        )
    return current


def _matches_type(instance: Any, schema_type: str) -> bool:
    return {
        "object": isinstance(instance, dict),
        "array": isinstance(instance, list),
        "string": isinstance(instance, str),
        "number": isinstance(instance, (int, float)) and not isinstance(instance, bool),
        "integer": isinstance(instance, int) and not isinstance(instance, bool),
        "boolean": isinstance(instance, bool),
        "null": instance is None,
    }[schema_type]


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isfinite(left) and math.isfinite(right) and left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _json_equal(left[key], right[key]) for key in left
        )
    return left == right


def _is_rfc3339_datetime(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() is not None and ("T" in value or "t" in value)


def _validate(
    instance: Any,
    schema: Any,
    *,
    root: dict[str, Any],
    instance_path: list[str | int],
    reference_stack: tuple[str, ...] = (),
) -> list[str]:
    if schema is True:
        return []
    if schema is False:
        return [f"{_json_path(instance_path)} is rejected by a false schema"]
    errors: list[str] = []
    if "$ref" in schema:
        reference = schema["$ref"]
        if reference in reference_stack:
            raise AttestationSchemaProfileError(
                f"cyclic local schema reference: {reference}"
            )
        errors.extend(
            _validate(
                instance,
                _resolve_local_reference(root, reference),
                root=root,
                instance_path=instance_path,
                reference_stack=(*reference_stack, reference),
            )
        )
    if "type" in schema and not _matches_type(instance, schema["type"]):
        errors.append(
            f"{_json_path(instance_path)} must have type {schema['type']}"
        )
        return errors
    if "const" in schema and not _json_equal(instance, schema["const"]):
        errors.append(f"{_json_path(instance_path)} does not match const")
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list):
            raise AttestationSchemaProfileError("enum must be an array")
        if not any(_json_equal(instance, allowed) for allowed in enum):
            errors.append(f"{_json_path(instance_path)} is not in enum")
    if isinstance(instance, dict):
        required = schema.get("required", [])
        for name in required:
            if name not in instance:
                errors.append(f"{_json_path([*instance_path, name])} is required")
        properties = schema.get("properties", {})
        for name, value in instance.items():
            if name in properties:
                errors.extend(
                    _validate(
                        value,
                        properties[name],
                        root=root,
                        instance_path=[*instance_path, name],
                    )
                )
            elif schema.get("additionalProperties") is False:
                errors.append(
                    f"{_json_path([*instance_path, name])} is not allowed"
                )
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(
                    _validate(
                        value,
                        schema["additionalProperties"],
                        root=root,
                        instance_path=[*instance_path, name],
                    )
                )
    if isinstance(instance, list):
        if "minItems" in schema:
            minimum = schema["minItems"]
            if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
                raise AttestationSchemaProfileError("minItems must be non-negative")
            if len(instance) < minimum:
                errors.append(
                    f"{_json_path(instance_path)} must contain at least {minimum} items"
                )
        if schema.get("uniqueItems") is True:
            serialized = [
                json.dumps(item, sort_keys=True, separators=(",", ":"))
                for item in instance
            ]
            if len(set(serialized)) != len(serialized):
                errors.append(f"{_json_path(instance_path)} items must be unique")
        if "items" in schema:
            for index, value in enumerate(instance):
                errors.extend(
                    _validate(
                        value,
                        schema["items"],
                        root=root,
                        instance_path=[*instance_path, index],
                    )
                )
        if "contains" in schema and not any(
            not _validate(
                value,
                schema["contains"],
                root=root,
                instance_path=[*instance_path, index],
            )
            for index, value in enumerate(instance)
        ):
            errors.append(
                f"{_json_path(instance_path)} has no item matching contains"
            )
    if isinstance(instance, str):
        if "minLength" in schema:
            minimum = schema["minLength"]
            if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
                raise AttestationSchemaProfileError("minLength must be non-negative")
            if len(instance) < minimum:
                errors.append(
                    f"{_json_path(instance_path)} must contain at least {minimum} characters"
                )
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{_json_path(instance_path)} does not match pattern")
        if schema.get("format") == "date-time" and not _is_rfc3339_datetime(instance):
            errors.append(f"{_json_path(instance_path)} is not an RFC 3339 date-time")
    for child in schema.get("allOf", []):
        errors.extend(
            _validate(
                instance,
                child,
                root=root,
                instance_path=instance_path,
            )
        )
    if "not" in schema and not _validate(
        instance,
        schema["not"],
        root=root,
        instance_path=instance_path,
    ):
        errors.append(f"{_json_path(instance_path)} matches prohibited schema")
    return errors


def validate_attestation_schema(
    instance: Any, schema: dict[str, Any]
) -> list[str]:
    """Return all validation errors under the fail-closed attestation profile."""

    if not isinstance(schema, dict):
        raise AttestationSchemaProfileError("attestation schema must be an object")
    _check_schema_shape(schema, path=[])
    return _validate(instance, schema, root=schema, instance_path=[])
