"""Bounded, low-authority execution of scientific connector fetches."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from research_machine.addons.models import AddonManifest, ScientificConnector
from research_machine.domain.errors import ValidationError

_MAX_CONNECTOR_OUTPUT_BYTES = 10_000_000


def fetch_source_proposal(
    manifest: AddonManifest,
    connector: ScientificConnector,
    query: dict[str, Any],
    *,
    max_bytes: int = _MAX_CONNECTOR_OUTPUT_BYTES,
) -> dict[str, Any]:
    """Run a connector and return source material for later canonical intake."""
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValidationError("connector max_bytes must be a positive integer")
    if not isinstance(query, dict):
        raise ValidationError("connector query must be an object")
    allowed = set(connector.required_query_fields) | set(connector.optional_query_fields)
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise ValidationError("connector query has unknown fields: " + ", ".join(unknown))
    missing = sorted(set(connector.required_query_fields) - set(query))
    if missing:
        raise ValidationError("connector query is missing fields: " + ", ".join(missing))
    result = connector.fetch(dict(query))
    if not isinstance(result, dict) or set(result) != {"bytes", "metadata"}:
        raise ValidationError("connector must return exactly bytes and metadata")
    source_bytes = result["bytes"]
    if not isinstance(source_bytes, bytes):
        raise ValidationError("connector bytes must be immutable bytes")
    if len(source_bytes) > max_bytes or len(source_bytes) > _MAX_CONNECTOR_OUTPUT_BYTES:
        raise ValidationError("connector output exceeds bounded byte limit")
    if not isinstance(result["metadata"], dict):
        raise ValidationError("connector metadata must be an object")
    try:
        metadata_bytes = len(
            json.dumps(
                result["metadata"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError("connector metadata must be JSON-compatible") from exc
    if metadata_bytes > max_bytes or metadata_bytes > _MAX_CONNECTOR_OUTPUT_BYTES:
        raise ValidationError("connector metadata exceeds bounded byte limit")
    return {
        "connector": {
            "addon_id": manifest.addon_id,
            "addon_version": manifest.version,
            "connector_id": connector.connector_id,
        },
        "query": query,
        "source": {
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "size_bytes": len(source_bytes),
            "bytes": source_bytes,
        },
        "metadata": result["metadata"],
        "authority": "bounded_source_material_proposal_only",
        "scientific_evidence_eligible": False,
        "canonical_dataset_registered": False,
        "custody_cleared": False,
        "authorized_actions": ["submit_to_canonical_dataset_intake"],
    }
